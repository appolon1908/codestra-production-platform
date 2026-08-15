# n8n and Odoo Connectivity

## Odoo

- Middleware -> Odoo network PASS: live `200 {"status":"pass"}` to `/web/health`.
- Odoo -> Middleware network PASS: live 200 from Odoo to control-plane `/health`.
- Functional/auth BLOCKED: Odoo has no control-plane credential and the control plane has no `CONTROL_PLANE_ODOO_URL`.
- No application direct Odoo PostgreSQL connection/write code was found. Audit SQL was read-only.
- `codestra_integration_hub` is installed, but no safe authenticated callback was available for a business-record test.

## n8n

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
