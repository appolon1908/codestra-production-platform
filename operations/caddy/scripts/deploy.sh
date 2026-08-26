#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/validate.sh"
STAMP=$(date -u +%Y%m%dT%H%M%SZ); SNAP="/var/backups/caddy/config-$STAMP"; mkdir -m 0700 -p "$SNAP"
cp -a /etc/caddy "$SNAP/"; cp -a /etc/systemd/system/caddy.service /etc/systemd/system/caddy.service.d "$SNAP/"
install -o root -g caddy -m 0640 "$ROOT/live/Caddyfile" /etc/caddy/Caddyfile
for area in sites conf.d snippets; do install -d -o root -g caddy -m 0750 "/etc/caddy/$area"; for f in "$ROOT/live/$area"/*.caddy; do install -o root -g caddy -m 0640 "$f" "/etc/caddy/$area/${f##*/}"; done; done
install -o root -g root -m 0644 "$ROOT/systemd/caddy.service" /etc/systemd/system/caddy.service
install -d -o root -g root -m 0755 /etc/systemd/system/caddy.service.d
install -o root -g root -m 0644 "$ROOT/systemd/caddy.service.d/production-hardening.conf" /etc/systemd/system/caddy.service.d/production-hardening.conf
install -o root -g root -m 0644 "$ROOT/logging/codestra-caddy.logrotate" /etc/logrotate.d/codestra-caddy
systemctl daemon-reload; caddy validate --config /etc/caddy/Caddyfile; systemctl reload caddy
systemctl is-active --quiet caddy; curl -fsS --max-time 10 https://api.codestra.co/healthz >/dev/null
echo "ACTIVE_CONFIG_BACKUP=$SNAP"; echo CADDY_DEPLOY=PASS
