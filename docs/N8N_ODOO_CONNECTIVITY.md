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

- Middleware -> n8n network PASS: live 200 to `/healthz`.
- n8n -> Middleware network PASS: live 200 from n8n to `/health`.
- Functional/auth remains BLOCKED outside this Odoo mission: the audited production database had 20 inactive workflows, zero webhook registrations, and zero credential records. Nothing was activated or deleted.
- Odoo and n8n use distinct service identities and credentials.
