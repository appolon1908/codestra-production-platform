# Control-plane API

All routes are HTTPS-only behind Kong host `api.codestra.co`, OIDC audience `codestra-control-plane`, body and rate limits, method allowlists, caller-specific scopes, `Idempotency-Key`, `X-Correlation-ID`, and tenant enforcement.

| Method | Path | Required scope | Meaning |
|---|---|---|---|
| POST | `/api/v1/control/campaigns` | `campaign.write` | Persist desired campaign and create job/outbox atomically |
| POST | `/api/v1/control/agents` | `agent.write` | Persist desired agent state |
| POST | `/api/v1/control/memberships` | `sync.execute` | Persist desired membership |
| POST | `/api/v1/control/adapters/execute` | `sync.execute` | Execute one allowlisted adapter command |
| POST | `/api/v1/results/jobs/{job_id}` | `sync.result.write` | Record unverified workflow result |
| GET | `/api/v1/control/jobs/{job_id}` | `mapping.read` | Read job state |
| POST | `/api/v1/reconciliation/run` | `reconciliation.execute` | Compare desired and actual state |
| GET | `/api/v1/reconciliation/*` | `reconciliation.read` | Read differences |

Same idempotency key and immutable payload returns the original result. A changed payload returns `409`. A delayed entity version returns `409 STALE_VERSION` and causes no mutation.
# Governed automation action handlers

`POST /api/v1/automation/execute` does not treat an approved action name as an
executed outcome. Each action is dispatched to the fixed URL named by
`CONTROL_PLANE_ACTION_<UPPERCASE_ACTION>_URL` (dots become underscores), using
an idempotency key bound to tenant, event, workflow, and action. Requests are
HMAC-SHA256 signed with the root-managed secret file selected by
`CONTROL_PLANE_AUTOMATION_ACTION_SECRET_FILE`.

The handler must return JSON containing the exact `action`, exact
`idempotency_key`, and `status: COMPLETED`. Middleware durably stores that
receipt. Exact retries reuse it; missing handlers, credentials, failed calls,
or mismatched receipts fail closed. The results endpoint rejects a `COMPLETED`
callback until every approved action has such a receipt.
