# Server 65 runtime contract probe

Date: 2026-09-03
Target: `65.109.65.169`
Access: loopback HTTP GETs through `codestra-app`; no credentials, bodies, or mutations.

| Service/port | health | readiness | version | capabilities | metrics | OpenAPI |
|---|---:|---:|---:|---:|---:|---:|
| middleware API / 8096 | 200 | 403 | 200 | 403 | 200 | 403 |
| reseller API / 18180 | 200 | 401 | 200 | 200 | 401 | 401 |
| portal / 18081 | 404 | 404 | 404 | 404 | 200 | 200 |
| Grafana / 3000 | 200 | 200 | 200 | 200 | 200 | 200 |
| Prometheus / 9090 | connection error | connection error | connection error | connection error | connection error | connection error |
| NATS monitor / 8222 | 404 | 404 | 404 | 404 | 404 | 404 |
| mail loopback / 28080 | connection error | connection error | connection error | connection error | connection error | connection error |
| Odoo UAT proxy / 19069 | 404 | 404 | 404 | 404 | 404 | 404 |
| middleware staging / 31883 | 404 | 404 | 200 | 404 | 200 | 200 |

HTTP 401/403 responses are recorded as auth boundaries, not treated as
successful unauthenticated contract probes. This probe does not establish
dependency readiness, authenticated OpenAPI parity, alert delivery, or
application monitoring coverage.

RUNTIME_CONTRACTS=FAIL
APPLICATION_MONITORING=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
