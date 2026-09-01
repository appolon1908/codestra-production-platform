#!/usr/bin/env sh
set -eu
admin="${KONG_ADMIN_URL:-http://127.0.0.1:8001}"
curl -fsS http://codestra-email-reseller-api-1:8080/health >/dev/null 2>&1 || true
curl -fsS -X PATCH "$admin/services/codestra-email-api" \
  --data protocol=http --data host=codestra-email-reseller-api-1 --data port=8080 >/dev/null
for plugin in $(curl -fsS "$admin/routes/email-route/plugins" | jq -r '.data[] | select(.name=="request-termination") | .id'); do
  curl -fsS -X DELETE "$admin/plugins/$plugin" >/dev/null
done
echo 'email route activated'
