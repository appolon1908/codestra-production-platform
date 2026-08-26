#!/usr/bin/env bash
set -euo pipefail
CONFIG=${CADDY_CONFIG:-/etc/caddy/Caddyfile}
KONG_ADMIN=${KONG_ADMIN_URL:-http://127.0.0.1:8001}
tmp=$(mktemp -d)
trap 'find "$tmp" -type f -delete 2>/dev/null || true; rmdir "$tmp" 2>/dev/null || true' EXIT

caddy adapt --config "$CONFIG" --adapter caddyfile >"$tmp/adapted.json" 2>"$tmp/adapt.err"
jq -r '.. | objects | select(.handler? == "reverse_proxy") | .upstreams[]?.dial' "$tmp/adapted.json" | sort -u >"$tmp/upstreams"
jq -r '.. | objects | .host? // empty | if type == "array" then .[] else . end' "$tmp/adapted.json" | sort -u >"$tmp/hosts"

fail=0
while read -r endpoint; do
  host=${endpoint%:*}; port=${endpoint##*:}
  if timeout 3 bash -c "</dev/tcp/$host/$port" 2>/dev/null; then
    echo "UPSTREAM=$endpoint TCP=PASS"
  else
    echo "UPSTREAM=$endpoint TCP=FAIL"
    fail=$((fail+1))
  fi
done <"$tmp/upstreams"

curl -fsS --max-time 5 "$KONG_ADMIN/routes?size=1000" >"$tmp/routes.json"
jq -r '.data[] | select((.hosts // []) | length > 0) | .hosts[]' "$tmp/routes.json" | sort -u |
while read -r host; do
  if grep -qx "$host" "$tmp/hosts"; then
    echo "KONG_HOST=$host CADDY=PASS"
  elif [ "$host" = kong-standby.internal.codestra.agency ]; then
    echo "KONG_HOST=$host CADDY=STANDBY_NOT_PUBLIC"
  else
    echo "KONG_HOST=$host CADDY=FAIL"
    fail=$((fail+1))
  fi
done

for port in 8000 18101; do
  if timeout 2 bash -c "</dev/tcp/65.109.65.169/$port" 2>/dev/null; then
    echo "PUBLIC_BYPASS_PORT=$port CLOSED=FAIL"
    fail=$((fail+1))
  else
    echo "PUBLIC_BYPASS_PORT=$port CLOSED=PASS"
  fi
done

echo "CADDY_ENDPOINT_PORT_ERRORS=$fail"
[ "$fail" -eq 0 ]
echo CADDY_ENDPOINT_PORT_AUDIT=PASS
