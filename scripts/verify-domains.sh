#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED_IP="${EXPECTED_IP:-65.109.65.169}"
OUTPUT="${1:-reports/app-server-a/DOMAIN_VERIFICATION.md}"

mkdir -p "$(dirname "$OUTPUT")"

resolve_a() {
  local host="$1"
  if command -v dig >/dev/null 2>&1; then
    dig +short "$host" A | awk 'NF'
  else
    getent ahostsv4 "$host" 2>/dev/null | awk '{print $1}' | sort -u
  fi
}

check_host() {
  local host="$1"
  local result status
  result="$(resolve_a "$host" | sort -u | paste -sd, - || true)"
  if [[ ",${result}," == *",${EXPECTED_IP},"* ]]; then
    status="PASS"
  elif [[ -z "$result" ]]; then
    status="UNRESOLVED"
  else
    status="MISMATCH"
  fi
  printf '| `%s` | `%s` | `%s` | `%s` |\n' "$host" "${result:-NONE}" "$EXPECTED_IP" "$status"
}

{
  printf '# Domain Verification\n\n'
  printf 'Generated UTC: `%s`\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '| Hostname | Resolved IPv4 | Expected IPv4 | Result |\n'
  printf '|---|---|---|---|\n'
  check_host crm.codestra.agency
  check_host api.codestra.agency
  check_host n8n.codestra.agency
  check_host auth.codestra.agency
  printf '\n'
  printf 'Public Keycloak activation is blocked unless `auth.codestra.agency` resolves to `%s`.\n' "$EXPECTED_IP"
} > "$OUTPUT"

cat "$OUTPUT"
