#!/usr/bin/env sh
set -eu
admin="${KONG_ADMIN_URL:-http://127.0.0.1:8001}"
curl -fsS -X PATCH "$admin/services/codestra-email-api" \
  --data protocol=http --data host=unconfigured.invalid --data port=80 >/dev/null
if ! curl -fsS "$admin/routes/email-route/plugins" | jq -e '.data[] | select(.name=="request-termination")' >/dev/null; then
  curl -fsS -X POST "$admin/routes/email-route/plugins" \
    --data name=request-termination --data config.status_code=503 \
    --data config.message='API middleware route is not activated' >/dev/null
fi
echo 'email route restored to fail-closed upstream'
