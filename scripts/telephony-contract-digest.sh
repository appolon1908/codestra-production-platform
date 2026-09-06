#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
files=(
  contracts/telephony/codestra-calling-api.v1.openapi.yaml
  contracts/telephony/codestra-calling-ecosystem.v1.yaml
  contracts/telephony/codestra-calling-events.v1.asyncapi.yaml
  schemas/integration-event-envelope-v1.schema.json
)
for file in "${files[@]}"; do test -f "$file" || { echo "missing $file" >&2; exit 1; }; done
digest="$(LC_ALL=C sha256sum "${files[@]}" | awk '{print $1 "  " $2}' | sha256sum | awk '{print $1}')"
printf '%s\n' "$digest"
