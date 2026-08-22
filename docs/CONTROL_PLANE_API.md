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
