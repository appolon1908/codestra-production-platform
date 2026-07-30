#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
for _ in $(seq 1 60); do
  if docker compose -f "$root/compose.yaml" exec -T asterisk asterisk -rx 'core show version' >/dev/null 2>&1; then exit 0; fi
  sleep 1
done
docker compose -f "$root/compose.yaml" logs --no-color
exit 1
