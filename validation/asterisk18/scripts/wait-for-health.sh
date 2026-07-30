#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
for _ in $(seq 1 60); do
  if docker compose -f "$root/compose.yaml" exec -T --user 10001:10001 asterisk \
    asterisk -rx 'core show version' >/dev/null 2>&1; then
    listeners=$(docker compose -f "$root/compose.yaml" exec -T asterisk \
      awk '$4 == "0A" { split($2, address, ":"); print address[2] }' /proc/net/tcp)
    ready=true
    for port_hex in 13AE 13AF 13B0 13B1 13B2 13B3; do
      if ! grep -qx "$port_hex" <<<"$listeners"; then ready=false; break; fi
    done
    if [[ "$ready" == true ]]; then exit 0; fi
  fi
  if [[ $(docker compose -f "$root/compose.yaml" ps --status exited --quiet asterisk) ]]; then break; fi
  sleep 1
done
docker compose -f "$root/compose.yaml" logs --no-color
exit 1
