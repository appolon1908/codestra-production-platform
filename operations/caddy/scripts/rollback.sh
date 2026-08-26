#!/usr/bin/env bash
set -euo pipefail
SNAP=${1:?rollback snapshot required}
[ -f "$SNAP/caddy/Caddyfile" ]
caddy validate --config "$SNAP/caddy/Caddyfile" --adapter caddyfile
cp -a "$SNAP/caddy/." /etc/caddy/
cp -a "$SNAP/caddy.service" /etc/systemd/system/caddy.service
cp -a "$SNAP/caddy.service.d/." /etc/systemd/system/caddy.service.d/
systemctl daemon-reload; caddy validate --config /etc/caddy/Caddyfile; systemctl reload caddy
curl -fsS --max-time 10 https://api.codestra.co/healthz >/dev/null
curl -sS --max-time 10 -o /dev/null -w '%{http_code}' https://api.codestra.co/ | grep -Eq '^(200|401|403|404)$'
echo CADDY_ROLLBACK=PASS
