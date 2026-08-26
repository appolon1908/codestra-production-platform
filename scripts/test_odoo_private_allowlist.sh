#!/usr/bin/env bash
set -euo pipefail

approved_container=${APPROVED_CONTAINER:-codestra-middleware-integration-api-1}
proxy_host=${PROXY_HOST:-odoo.internal.codestra.agency}

probe() {
  local method=$1 path=$2 expected=$3
  local code
  code=$(docker exec "${approved_container}" /opt/venv/bin/python3 -c '
import ssl, sys, urllib.error, urllib.request
request = urllib.request.Request(sys.argv[2], method=sys.argv[1])
try:
    response = urllib.request.urlopen(
        request, timeout=10, context=ssl._create_unverified_context()
    )
    print(response.status)
except urllib.error.HTTPError as error:
    print(error.code)
' "${method}" "https://${proxy_host}${path}")
  case ",${expected}," in
    *,"${code}",*) ;;
    *) printf 'FAIL method=%s path=%s status=%s expected=%s\n' \
         "${method}" "${path}" "${code}" "${expected}" >&2; return 1 ;;
  esac
}

# Allowed routes reach either a healthy endpoint or the Odoo authentication
# boundary. Synthetic probes do not submit a valid credential or business data.
probe GET  /web/health 200
probe HEAD /web/health 200
probe POST /api/v1/integration/results 401,403
probe POST /codestra/api/v1/call-events 401,403

# Method/path combinations outside the explicit contract fail closed.
probe GET  /api/v1/integration/results 404
probe POST /web/health 404
probe GET  / 404
probe POST /web/login 404
probe GET  /web/database/list 404
probe GET  /not-a-real-odoo-route 404

printf 'ODOO_PRIVATE_INTEGRATION_ALLOWLIST=PASS\n'
