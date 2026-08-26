# API Endpoint Matrix

## Control plane (`127.0.0.1:8096`)

| Method/path | Class / purpose | Auth | Validation / trace | Downstream |
|---|---|---|---|---|
| GET `/health`, `/v1/health`, `/ready`, `/v1/ready`, `/metrics` | health/monitoring | none; private binding | state-store readiness | process/SQLite |
| POST `/api/v1/events/{source}`, `/v1/events` | webhook ingress for five systems | service bearer + HMAC + timestamp | source prefix, tenant, event ID, idempotency key, correlation | Odoo/n8n ledger |
| POST `/v1/messages/sms`, `/email` | internal messaging | operator bearer | tenant, consent/suppression, request/correlation/idempotency headers | Telnexa/Klyrow safe adapter |
| GET `/v1/messages[/{id}[/events]]` | tenant ledger | operator bearer | tenant scoped | SQLite |
| PUT/POST `/v1/customers/{id}/preferences` | preferences | operator bearer | tenant scoped and audited | SQLite |
| POST `/api/v1/preferences[/check]` | preference update/check | operator bearer | tenant scoped and audited | SQLite |
| GET `/api/v1/ops/summary`, `/events`, `/correlations/{id}` | operations | role bearer | optional tenant scope | SQLite |
| POST `/api/v1/ops/events/{id}/replay` | DLQ replay | privileged bearer | state gated and audited | queue |
| POST `/api/v1/ops/integrations/{name}/{pause,resume}` | kill switch | privileged bearer | allowlisted and audited | integration state |

Live negative tests proved missing/invalid bearer, invalid HMAC, stale timestamp, replay, and idempotency-conflict rejection for Odoo, n8n, Telnexa, Klyrow, and Kyqra.

## Private gateway (`10.40.0.1:8095`)

All POST routes require a service bearer, service-specific HMAC, exact source, fresh timestamp, and event ID. Every route was exercised live.

| System | Routes |
|---|---|
| Kyqra | `/api/v1/kyqra/jobs`, `/results`, `/progress`, `/failures`, `/health` |
| Telnexa | `/api/v1/telnexa/inbound`, `/dlr`, `/failure`, `/provider-status`, `/health` |
| Klyrow | `/api/v1/klyrow/campaigns`, `/contacts`, `/events`, `/bounces`, `/complaints`, `/unsubscribes`, `/health` |

Events enter SQLite with five-attempt bounded exponential retry and terminal `dead_letter`. Kyqra entity keys deduplicate classifications/results.

## Restricted VICIdial adapter (`10.40.0.2:8443`)

Observed live `/health` and `/ready` over mTLS. Source declares `/version`, campaign validate/provision/update/disable/read-back, agent sync/disable/read-back, lead publish/read-back, callback create/read-back, script/disposition/transfer-policy sync, and reconciliation routes. Mutations were not invoked.
