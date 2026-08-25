#!/usr/bin/env bash
set -uo pipefail

# Read-only Kong/Caddy/middleware readiness audit. Output is redacted by default.
# Secrets are accepted only through files and are never printed.

umask 077

show_topology=false
include_logs=false
insecure_local_tls=false
output_file=""
KONG_ADMIN_URL=${KONG_ADMIN_URL:-}
KONG_ADMIN_CA_FILE=${KONG_ADMIN_CA_FILE:-}
KONG_ADMIN_CLIENT_CERT=${KONG_ADMIN_CLIENT_CERT:-}
KONG_ADMIN_CLIENT_KEY=${KONG_ADMIN_CLIENT_KEY:-}
KONG_ADMIN_TOKEN_FILE=${KONG_ADMIN_TOKEN_FILE:-}
KONG_ADMIN_HEADER_NAME=${KONG_ADMIN_HEADER_NAME:-Kong-Admin-Token}
KONG_PAGE_SIZE=${KONG_PAGE_SIZE:-100}
KONG_MAX_PAGES=${KONG_MAX_PAGES:-0}

usage() {
  cat <<'EOF'
Usage: kong-caddy-middleware-audit.sh [options]

Options:
  --admin-url URL          Explicit Kong Admin API base URL
  --ca-file PATH           CA bundle used to verify the Admin API certificate
  --client-cert PATH       Admin API mTLS client certificate
  --client-key PATH        Admin API mTLS client private key
  --token-file PATH        File containing the Admin API token
  --header-name NAME       Token header (default: Kong-Admin-Token)
  --page-size NUMBER       Kong inventory page size (default: 100)
  --max-pages NUMBER       Safety limit; 0 means unlimited (default: 0)
  --show-topology          Print container, network, route, and upstream details
  --include-logs           Include filtered recent logs (may contain sensitive data)
  --insecure-local-tls     Permit -k for local HTTPS discovery (not recommended)
  --output PATH            Write mode-0600 output instead of stdout
  -h, --help               Show this help

Authentication material is read from files so it is not exposed in argv or output.
EOF
}

die() {
  printf 'ERROR=%s\n' "$1" >&2
  exit 2
}

require_readable() {
  local value=$1 label=$2
  [ -z "$value" ] || [ -r "$value" ] || die "${label}_NOT_READABLE"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --admin-url) [ "$#" -ge 2 ] || die MISSING_ADMIN_URL; KONG_ADMIN_URL=$2; shift 2 ;;
    --ca-file) [ "$#" -ge 2 ] || die MISSING_CA_FILE; KONG_ADMIN_CA_FILE=$2; shift 2 ;;
    --client-cert) [ "$#" -ge 2 ] || die MISSING_CLIENT_CERT; KONG_ADMIN_CLIENT_CERT=$2; shift 2 ;;
    --client-key) [ "$#" -ge 2 ] || die MISSING_CLIENT_KEY; KONG_ADMIN_CLIENT_KEY=$2; shift 2 ;;
    --token-file) [ "$#" -ge 2 ] || die MISSING_TOKEN_FILE; KONG_ADMIN_TOKEN_FILE=$2; shift 2 ;;
    --header-name) [ "$#" -ge 2 ] || die MISSING_HEADER_NAME; KONG_ADMIN_HEADER_NAME=$2; shift 2 ;;
    --page-size) [ "$#" -ge 2 ] || die MISSING_PAGE_SIZE; KONG_PAGE_SIZE=$2; shift 2 ;;
    --max-pages) [ "$#" -ge 2 ] || die MISSING_MAX_PAGES; KONG_MAX_PAGES=$2; shift 2 ;;
    --show-topology) show_topology=true; shift ;;
    --include-logs) include_logs=true; shift ;;
    --insecure-local-tls) insecure_local_tls=true; shift ;;
    --output) [ "$#" -ge 2 ] || die MISSING_OUTPUT; output_file=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "UNKNOWN_OPTION_$1" ;;
  esac
done

[[ "$KONG_PAGE_SIZE" =~ ^[1-9][0-9]*$ ]] || die INVALID_PAGE_SIZE
[[ "$KONG_MAX_PAGES" =~ ^[0-9]+$ ]] || die INVALID_MAX_PAGES
[[ "$KONG_ADMIN_HEADER_NAME" =~ ^[A-Za-z0-9-]+$ ]] || die INVALID_HEADER_NAME
if { [ -n "$KONG_ADMIN_CLIENT_CERT" ] && [ -z "$KONG_ADMIN_CLIENT_KEY" ]; } \
  || { [ -z "$KONG_ADMIN_CLIENT_CERT" ] && [ -n "$KONG_ADMIN_CLIENT_KEY" ]; }; then
  die CLIENT_CERT_AND_KEY_REQUIRED_TOGETHER
fi
require_readable "$KONG_ADMIN_CA_FILE" CA_FILE
require_readable "$KONG_ADMIN_CLIENT_CERT" CLIENT_CERT
require_readable "$KONG_ADMIN_CLIENT_KEY" CLIENT_KEY
require_readable "$KONG_ADMIN_TOKEN_FILE" TOKEN_FILE

if [ -n "$output_file" ]; then
  output_dir=$(dirname -- "$output_file")
  [ -d "$output_dir" ] || die OUTPUT_DIRECTORY_NOT_FOUND
  : >"$output_file" || die OUTPUT_NOT_WRITABLE
  chmod 600 "$output_file" || die OUTPUT_CHMOD_FAILED
  exec >"$output_file"
fi

status_file=$(mktemp) || die UNABLE_TO_CREATE_TEMP_FILE
trap 'rm -f "$status_file"' EXIT

CURL_ARGS=(-fsS --connect-timeout 3 --max-time 10)
[ -z "$KONG_ADMIN_CA_FILE" ] || CURL_ARGS+=(--cacert "$KONG_ADMIN_CA_FILE")
[ -z "$KONG_ADMIN_CLIENT_CERT" ] || CURL_ARGS+=(--cert "$KONG_ADMIN_CLIENT_CERT" --key "$KONG_ADMIN_CLIENT_KEY")
if [ -n "$KONG_ADMIN_TOKEN_FILE" ]; then
  token=$(<"$KONG_ADMIN_TOKEN_FILE")
  [ -n "$token" ] || die EMPTY_TOKEN_FILE
  CURL_ARGS+=(--header "$KONG_ADMIN_HEADER_NAME: $token")
  unset token
fi

declare -a KONG_CONTAINERS=()
discover_kong_containers() {
  local id image service process
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    image=$(docker inspect "$id" --format '{{.Config.Image}}' 2>/dev/null) || continue
    service=$(docker inspect "$id" --format '{{index .Config.Labels "com.docker.compose.service"}}' 2>/dev/null || true)
    process=$(docker inspect "$id" --format '{{json .Config.Entrypoint}} {{json .Config.Cmd}}' 2>/dev/null || true)
    if grep -Eiq '(^|[./])kong/kong-gateway([:@._-]|$)|^kong([:@]|$)' <<<"$image" \
      || grep -Eiq '^(kong|kong-gateway|kong-cp|kong-dp)$' <<<"$service" \
      || grep -Eiq '(^|[" /])kong([" /]|$)' <<<"$process" \
      || docker inspect "$id" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | grep -Eq '^KONG_(DATABASE|ROLE|ADMIN_LISTEN|PROXY_LISTEN|STREAM_LISTEN|PREFIX|DECLARATIVE_CONFIG|NGINX_[A-Z0-9_]+)='; then
      KONG_CONTAINERS+=("$id")
    fi
  done < <(docker ps -aq 2>/dev/null || true)
}

container_name() {
  docker inspect "$1" --format '{{.Name}}' 2>/dev/null | sed 's#^/##'
}

redacted_container() {
  local index=$1 id=$2
  if $show_topology; then container_name "$id"; else printf 'KONG_CONTAINER_%s' "$index"; fi
}

admin_get() {
  local url=$1
  local -a args=("${CURL_ARGS[@]}")
  if $insecure_local_tls && [[ "$url" == https://127.0.0.1:* || "$url" == https://localhost:* ]]; then
    args+=(-k)
  fi
  curl "${args[@]}" "$url"
}

discover_admin() {
  local candidate
  if [ -n "$KONG_ADMIN_URL" ]; then
    KONG_ADMIN_URL=${KONG_ADMIN_URL%/}
    admin_get "$KONG_ADMIN_URL/status" >"$status_file" 2>/dev/null
    return $?
  fi
  for candidate in http://127.0.0.1:8001 https://127.0.0.1:8444; do
    if admin_get "$candidate/status" >"$status_file" 2>/dev/null; then
      KONG_ADMIN_URL=$candidate
      return 0
    fi
  done
  return 1
}

kong_paginate() {
  local endpoint=$1 jq_filter=$2 label=$3
  local next_url="$KONG_ADMIN_URL/$endpoint?size=$KONG_PAGE_SIZE"
  local response next page=0 item_count=0
  declare -A visited=()
  while [ -n "$next_url" ]; do
    if [ -n "${visited[$next_url]+x}" ]; then
      printf '%s=PAGINATION_LOOP_DETECTED\n' "$label"
      return 1
    fi
    visited[$next_url]=1
    page=$((page + 1))
    if [ "$KONG_MAX_PAGES" -gt 0 ] && [ "$page" -gt "$KONG_MAX_PAGES" ]; then
      printf '%s=PAGINATION_LIMIT_REACHED\n' "$label"
      return 1
    fi
    if ! response=$(admin_get "$next_url" 2>/dev/null) || [ -z "$response" ]; then
      printf '%s=UNAVAILABLE_OR_UNAUTHORIZED\n' "$label"
      return 1
    fi
    if ! jq -e '.data | type == "array"' >/dev/null 2>&1 <<<"$response"; then
      printf '%s=INVALID_RESPONSE\n' "$label"
      return 1
    fi
    item_count=$((item_count + $(jq '.data | length' <<<"$response")))
    if $show_topology; then
      jq -r "$jq_filter" <<<"$response" || return 1
    fi
    next=$(jq -er '.next // "" | strings' <<<"$response" 2>/dev/null) || {
      printf '%s=INVALID_NEXT_VALUE\n' "$label"
      return 1
    }
    if [ -z "$next" ]; then
      next_url=""
    elif [[ "$next" == "$KONG_ADMIN_URL/"* ]]; then
      next_url=$next
    elif [[ "$next" == /* ]]; then
      next_url="${KONG_ADMIN_URL}${next}"
    elif [[ "$next" != *://* ]]; then
      next_url="${KONG_ADMIN_URL}/${next}"
    else
      printf '%s=UNSAFE_PAGINATION_URL\n' "$label"
      return 1
    fi
  done
  printf '%s_COUNT=%s\n%s_PAGES=%s\n' "$label" "$item_count" "$label" "$page"
}

discover_kong_containers

echo '========================================'
echo 'KONG / CADDY / MIDDLEWARE READINESS AUDIT'
echo '========================================'
echo 'OUTPUT_CLASSIFICATION=SENSITIVE_OPERATIONAL'
echo "TOPOLOGY_REDACTED=$([ "$show_topology" = true ] && echo false || echo true)"
echo "RECENT_LOGS_INCLUDED=$include_logs"
echo "LOCAL_TLS_VERIFICATION=$([ "$insecure_local_tls" = true ] && echo BYPASSED || echo ENFORCED)"

echo
echo '### 1. KONG CONTAINERS'
printf 'KONG_CONTAINER_COUNT=%s\n' "${#KONG_CONTAINERS[@]}"
for index in "${!KONG_CONTAINERS[@]}"; do
  id=${KONG_CONTAINERS[$index]}
  label=$(redacted_container "$((index + 1))" "$id")
  docker inspect "$id" --format "$label|IMAGE={{.Config.Image}}|STATUS={{.State.Status}}|HEALTH={{if .State.Health}}{{.State.Health.Status}}{{else}}NONE{{end}}|RESTARTS={{.RestartCount}}"
  if $show_topology; then
    docker inspect "$id" --format 'PROJECT={{index .Config.Labels "com.docker.compose.project"}} SERVICE={{index .Config.Labels "com.docker.compose.service"}} NETWORKS={{range $name,$net := .NetworkSettings.Networks}}{{$name}}={{$net.IPAddress}} {{end}}'
  fi
done

echo
echo '### 2. HOST LISTENERS / ADMIN EXPOSURE'
ss -lntp 2>/dev/null | grep -E ':(8000|8443|8001|8444)\b' || echo 'KONG_STANDARD_LISTENERS=NONE'
ss -lntp 2>/dev/null | grep -E '(^|[[:space:]])(0\.0\.0\.0|\*|\[::\]|\[\*\]):(8001|8444)([[:space:]]|$)' \
  || echo 'KONG_ADMIN_PUBLIC_BIND=NONE'

echo
echo '### 3. KONG ADMIN STATUS'
if discover_admin; then
  echo "KONG_ADMIN_API=$KONG_ADMIN_URL"
  echo "KONG_ADMIN_AUTH=$([ -n "$KONG_ADMIN_TOKEN_FILE$KONG_ADMIN_CLIENT_CERT" ] && echo CONFIGURED || echo NONE)"
  if $show_topology; then
    jq . "$status_file" 2>/dev/null || echo 'KONG_STATUS_RESPONSE=NON_JSON'
  else
    jq -r '
      "KONG_DATABASE_REACHABLE=" + ((.database.reachable // "UNKNOWN") | tostring),
      "KONG_CONNECTIONS_ACTIVE=" + ((.server.connections_active // "UNKNOWN") | tostring),
      "KONG_TOTAL_REQUESTS=" + ((.server.total_requests // "UNKNOWN") | tostring)
    ' "$status_file" 2>/dev/null || echo 'KONG_STATUS_RESPONSE=NON_JSON'
  fi
else
  echo 'KONG_ADMIN_API=UNAVAILABLE_OR_AUTH_REQUIRED'
fi

echo
echo '### 4. KONG ADMIN INVENTORY'
if [ -n "$KONG_ADMIN_URL" ] && [ -s "$status_file" ]; then
  kong_paginate services '.data[] | [.name,.protocol,.host,(.port|tostring),(.path // "")] | @tsv' SERVICES || true
  kong_paginate routes '.data[] | [.name,((.protocols // [])|join(",")),((.hosts // [])|join(",")),((.paths // [])|join(",")),(.service.id // "")] | @tsv' ROUTES || true
  kong_paginate plugins '.data[] | [.name,(.instance_name // ""),(.enabled|tostring),(.route.id // ""),(.service.id // ""),(.consumer.id // "")] | @tsv' PLUGINS || true
else
  echo 'KONG_INVENTORY=SKIPPED'
fi

echo
echo '### 5. RECENT KONG ERRORS'
if $include_logs; then
  for index in "${!KONG_CONTAINERS[@]}"; do
    id=${KONG_CONTAINERS[$index]}
    printf '%s\n' "--- $(redacted_container "$((index + 1))" "$id") ---"
    docker logs --since 6h "$id" 2>&1 \
      | grep -Ei 'error|failed|timeout|upstream|502|503|504|database|connect|refused' \
      | tail -150 || true
  done
else
  echo 'KONG_RECENT_ERRORS=REDACTED_USE_--include-logs'
fi

echo
echo '### 6. CADDY / MIDDLEWARE CONNECTIVITY HINTS'
echo 'CADDY_CONFIG_VALIDATE=RUN_SEPARATELY_ON_ACTIVE_CADDY_HOST_OR_CONTAINER'
echo 'END_TO_END_CANARY=REQUIRED_CLIENT_TO_CADDY_TO_KONG_TO_MIDDLEWARE'

echo
echo '========================================'
echo 'KONG AUDIT COMPLETE'
echo '========================================'
