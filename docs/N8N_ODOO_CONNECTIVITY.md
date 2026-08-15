# n8n and Odoo Connectivity

## Odoo

Status on 2026-08-15: **functional PASS in both directions**.

### Runtime identity and routing

- Middleware -> Odoo uses the dedicated Odoo user `codestra.middleware@service.internal` (database user ID 59) and the least-privilege `Codestra Middleware Bridge` group. It does not reuse any n8n, Telnexa, Klyrow, or Kyqra identity.
- Odoo -> Middleware uses its own bearer key and HMAC secret in Odoo system parameters. Middleware ingress uses the matching `ODOO_MIDDLEWARE_API_KEY` and `ODOO_WEBHOOK_SECRET` runtime secrets.
- Secrets are outside Git: middleware values are loaded from `/etc/codestra/secrets/control-plane.env`; Odoo values are stored through `ir.config_parameter` using the Odoo ORM. Secret values must never be copied into this repository or logs.
- The discovered Docker-private event endpoint is `http://codestra-odoo-1:8069/codestra/api/v1/events`. The controlled contact API is rooted at `http://codestra-odoo-1:8069/codestra/middleware/v1`.
- Odoo calls `http://codestra-integration-control-plane-api-1:8096/api/v1/events/odoo` on the shared `codestra_edge` Docker network.
- The bridge add-on must be deployed in the persistent host directory mounted as `/mnt/integration-addons`, not only `/mnt/extra-addons`, because the production Odoo command explicitly loads `/mnt/integration-addons` and `/mnt/call-center-addons`.

### Middleware -> Odoo evidence

The live suite ran from the control-plane API container against production Odoo, using only uniquely tagged `CODESTRA-INTEGRATION-TEST-*` data:

| Check | Result | Live evidence |
|---|---|---|
| Health | PASS | `/web/health` returned 200 |
| Authenticated create | PASS | HTTP 201, synthetic partner 114 |
| Authenticated read | PASS | HTTP 200, returned the tagged partner |
| Authenticated update | PASS | HTTP 200, synthetic phone update only |
| Communication/activity | PASS | HTTP 201, synthetic activity 16 |
| Status update | PASS | HTTP 200, `test -> active -> inactive` |
| Correlation | PASS | Every response echoed the request correlation ID; Odoo event/audit entries were written |
| Idempotency | PASS | Same key/body with a fresh event ID returned 200 and `duplicate: true` without a second mutation |
| Replay | PASS | Reused event ID returned 409 `replayed_event_id` |
| Invalid credential | PASS | Bad HMAC returned 401 `invalid_signature` |
| Timeout/retry/DLQ | PASS | Isolated unreachable Odoo target reached `dead_letter` after exactly 5 bounded attempts (`URLError`) |

The contact API refuses untagged contacts and will not read or mutate unrelated partners. Its ACL grants read/write/create only where required and no unlink permission.

### Odoo -> Middleware evidence

The live test was initiated inside the Odoo container through `codestra.middleware.outbound`:

- Signed `customer.updated` synthetic event returned HTTP 202 and was queued with its correlation and idempotency IDs intact.
- Exact reuse of the signed event ID returned 409 `replayed_event_id`.
- A legitimate retry with a fresh event ID and the same idempotency key returned 200 with `duplicate: true` and did not create a second event.
- A wrong bearer key returned 401 `invalid_api_key`; a wrong HMAC returned 401 `invalid_signature`.
- Odoo recorded its outbound event and audit entry through the approved ORM models.

### Safety and data path

No code in the bridge opens a PostgreSQL connection. All Odoo reads and writes use models/controllers and the Odoo ORM. No unrelated record was modified, no record was deleted, and no direct Odoo PostgreSQL write was performed. Tenant matching is pinned to `codestra-production`; mismatched tenants are rejected before model access.

## n8n

- Mission 2 live revalidation (2026-08-15 14:08 UTC): the runtime export contained 34 workflows, with exactly the 13 required event workflows and `CP-90-STANDARD-ERROR-V1` active. All 20 pre-existing workflows remained preserved and inactive. Focused integration tests passed 14/14 and the safe connectivity audit run `20260815T140813Z-b2579672` passed 93/93 with zero failures.
- Middleware -> n8n network PASS: live 200 to `/healthz`.
- n8n -> Middleware network PASS: live 200 from n8n to `/health`.
- Middleware -> n8n functional PASS (2026-08-15): the private target is `http://codestra-n8n-1:5678/webhook/codestra-{event_type}`. All 13 governed endpoints returned 200 with the dedicated header credential, rejected invalid auth with 403, preserved correlation/tenant/customer IDs, and suppressed a duplicate delivery. A fresh event under correlation `live-worker-corr-d21d2d4fbbee4909b40c88fdb59464fe` traversed the deployed middleware worker and was read back `delivered` with zero retries.
- n8n -> Middleware functional PASS (2026-08-15): a request originated inside `codestra-n8n-1` and reached `http://codestra-integration-control-plane-api-1:8096/api/v1/events/n8n`. Valid bearer+HMAC returned 202, invalid bearer/HMAC and an expired replay returned 401, and a second event with the same idempotency key returned 200 with `duplicate=true`. Correlation read-back matched.
- `N8N_MIDDLEWARE_API_KEY` and `N8N_MIDDLEWARE_HMAC_SECRET` are projected into n8n from `/opt/codestra/env/n8n.env`; middleware delivery credentials and `CONTROL_PLANE_N8N_URL` are in `/etc/codestra/secrets/control-plane.env`. Both files are outside Git and mode 0600. Values are not recorded in exports or evidence.
- Middleware owns authentication, replay defense, persistence, bounded retry (five attempts), DLQ, and routing. Workflows perform no direct database writes and contain no embedded secrets.

### Active governed workflows

| Event | Workflow | Webhook path |
|---|---|---|
| `sms.received` | `CP-20-SMS.RECEIVED-V1` | `/webhook/codestra-sms-received` |
| `sms.delivered` | `CP-21-SMS.DELIVERED-V1` | `/webhook/codestra-sms-delivered` |
| `sms.failed` | `CP-22-SMS.FAILED-V1` | `/webhook/codestra-sms-failed` |
| `sms.opted_out` | `CP-23-SMS.OPTED_OUT-V1` | `/webhook/codestra-sms-opted_out` |
| `email.delivered` | `CP-24-EMAIL.DELIVERED-V1` | `/webhook/codestra-email-delivered` |
| `email.bounced` | `CP-25-EMAIL.BOUNCED-V1` | `/webhook/codestra-email-bounced` |
| `email.complained` | `CP-26-EMAIL.COMPLAINED-V1` | `/webhook/codestra-email-complained` |
| `email.unsubscribed` | `CP-27-EMAIL.UNSUBSCRIBED-V1` | `/webhook/codestra-email-unsubscribed` |
| `crawler.result.created` | `CP-28-CRAWLER.RESULT.CREATED-V1` | `/webhook/codestra-crawler-result-created` |
| `crawler.job.completed` | `CP-29-CRAWLER.JOB.COMPLETED-V1` | `/webhook/codestra-crawler-job-completed` |
| `crawler.job.failed` | `CP-30-CRAWLER.JOB.FAILED-V1` | `/webhook/codestra-crawler-job-failed` |
| `customer.created` | `CP-31-CUSTOMER.CREATED-V1` | `/webhook/codestra-customer-created` |
| `customer.updated` | `CP-32-CUSTOMER.UPDATED-V1` | `/webhook/codestra-customer-updated` |
| workflow failures | `CP-90-STANDARD-ERROR-V1` | error-trigger subflow; no public webhook |

The 20 previously existing workflows were inventoried and preserved. None is active. Only the 14 entries above are published; the manifest and deterministic import remain inactive by default so activation stays an explicit acceptance-gated deployment step.

Odoo and n8n use distinct service identities and credentials.
