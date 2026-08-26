#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
count=0
compare() { if ! cmp -s "$1" "$2"; then echo "DRIFT $2"; count=$((count+1)); fi; }
compare "$ROOT/live/Caddyfile" /etc/caddy/Caddyfile
for area in sites conf.d snippets; do
  while IFS= read -r source; do target="/etc/caddy/$area/${source##*/}"; if [ ! -f "$target" ]; then echo "MISSING $target"; count=$((count+1)); else compare "$source" "$target"; fi; done < <(find "$ROOT/live/$area" -maxdepth 1 -type f -name '*.caddy' | sort)
  while IFS= read -r live; do source="$ROOT/live/$area/${live##*/}"; if [ ! -f "$source" ]; then echo "UNTRACKED $live"; count=$((count+1)); fi; done < <(find "/etc/caddy/$area" -maxdepth 1 -type f -name '*.caddy' | sort)
done
compare "$ROOT/systemd/caddy.service" /etc/systemd/system/caddy.service
compare "$ROOT/systemd/caddy.service.d/production-hardening.conf" /etc/systemd/system/caddy.service.d/production-hardening.conf
compare "$ROOT/logging/codestra-caddy.logrotate" /etc/logrotate.d/codestra-caddy
echo "CADDY_UNEXPECTED_DRIFT=$count"
[ "$count" -eq 0 ]
