# API Endpoint Matrix

| Method | Path | Class | Auth / scope | Idempotency / correlation | Downstream |
|---|---|---|---|---|---|
| GET | `/health`, `/v1/health` | health | public private-ingress | N/A | process only |
| GET | `/ready`, `/v1/ready` | readiness | public private-ingress | N/A | SQLite/provider mode |
| GET | `/metrics` | monitoring | ingress must restrict | N/A | SQLite |
| POST | `/v1/events` | event ingress | service bearer + HMAC; source header | event ID + tenant/source/key; correlation stored | Odoo/n8n |
| POST | `/api/v1/events/{source}` | event ingress | service bearer + HMAC | same | Odoo/n8n |
| POST | `/v1/messages/sms` | private write | operator bearer; tenant scoped | `Idempotency-Key`; request/correlation headers | Telnexa |
| POST | `/v1/messages/email` | private write | operator bearer; tenant scoped | same | Klyrow |
| POST | `/v1/crawler/jobs` | private write | operator bearer; tenant scoped | key + correlation; safe targets | Kyqra |
| GET | `/v1/crawler/jobs/{id}` | private read | operator bearer; tenant scoped | N/A | SQLite |
| GET | `/v1/messages[/{id}][/events]` | private read | operator bearer; tenant scoped | correlation visible | SQLite |
| POST | `/v1/messages/{id}/cancel`, `/retry` | admin mutation | operator bearer; tenant scoped | state machine/audit | worker/provider |
| GET/PUT | `/v1/customers/{id}/preferences` | private read/write | operator bearer; tenant scoped | primary key upsert; correlation audit | SQLite |
| POST | `/api/v1/preferences[/check]` | internal | operator bearer; tenant scoped | upsert/default deny | SQLite |
| GET | `/api/v1/ops/summary`, `/events`, `/correlations/{id}` | operations | role bearer; tenant filtering | N/A | SQLite |
| POST | `/api/v1/ops/events/{id}/replay` | operations | privileged bearer | bounded replay + audit | worker |
| POST | `/api/v1/ops/integrations/{name}/pause|resume` | operations | privileged bearer | explicit state + audit | delivery worker |

Unknown routes return 404; missing/invalid operator credentials return 403; missing/invalid service credentials return 401; validation errors return 422; idempotency conflicts return 409.
