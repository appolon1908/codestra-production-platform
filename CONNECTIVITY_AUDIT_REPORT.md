# Middleware API Connectivity Audit Report

Final validation: 2026-08-15 UTC
Branch: `agent/middleware-n8n-control-plane`
Safe audit evidence: `artifacts/connectivity-audit.json` (`20260815T132137Z-82b67ab3`, 93 PASS / 0 FAIL)
Repository validation: 196 tests and 9 subtests PASS.

## Outcome

Every locally repairable integration path is PASS in the non-production scope. The live private stack now has separate Odoo and n8n service identities, signed inbound requests, authenticated outbound delivery, 13 required event workflows plus one common error workflow, explicit private delivery targets, and the complete Kyqra job-control adapter. No real SMS, bulk email, production crawl, direct database write, or unrelated production-record mutation occurred.

Live correlation `final-pass-0121173014` delivered all required Telnexa, Klyrow, Kyqra, and customer events to their applicable Odoo and n8n targets with zero retries. Odoo JSON-RPC evidence created/read/updated tagged partner `CODESTRA_CONNECTIVITY_TEST_e6bc729f65` and activity 15 through the dedicated service user. Odoo -> Middleware returned 202 under correlation `odoo-live-232958819a9044ce8aa2d347276bf030`; n8n -> Middleware returned 202 under correlation `n8n-live-5148cef9-4b4b-4310-85cc-1b665d22d725`. Kyqra safe job `c6957821-7e9a-4a49-949b-bfac23e64165` passed create, duplicate replay, status, results, cancel, retry, and invalid-auth tests.

## Final matrix

`PASS` is based on live execution plus read-back, not configuration presence. Private Docker HTTP is marked PASS where it is an intentionally isolated same-host network boundary; public exposure was not added.

| Integration | NETWORK | AUTH | TLS/mTLS | API | HMAC | IDEMPOTENCY | CORRELATION ID | RETRY | DLQ | CIRCUIT BREAKER | END-TO-END TEST | FINAL STATUS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Odoo -> Middleware | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Middleware -> Odoo | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| n8n -> Middleware | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Middleware -> n8n | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Telnexa -> Middleware | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Middleware -> Telnexa | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Klyrow -> Middleware | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Middleware -> Klyrow | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Kyqra -> Middleware | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| Middleware -> Kyqra | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

## Live workflow evidence

- Odoo: dedicated active service user, HMAC event receiver fixed for the installed model schema, contact CRUD and activity creation read back live. Tagged records remain identifiable for controlled cleanup.
- n8n: all 13 required event workflows plus `CP-90-STANDARD-ERROR-V1` were imported with a credential reference and published. Every event webhook returned HTTP 200 for valid auth and duplicate replay while preserving correlation, tenant, and customer context. Invalid auth returned 403. The 20 unrelated workflows remain preserved and inactive. Endpoint details are in `docs/N8N_ODOO_CONNECTIVITY.md`.
- Telnexa: simulator outbound and signed inbound/DLR paths passed. No carrier submission occurred.
- Klyrow: safe/test outbound and signed delivered/bounced/unsubscribed paths passed. Only `.invalid`/tagged test data was used; no bulk delivery occurred.
- Kyqra: safe adapter passed create/status/results/cancel/retry, correlation/request/idempotency propagation, duplicate replay, and invalid auth. Results normalized once and were delivered to n8n and Odoo.
- Failure controls: n8n -> Middleware live evidence returned 202 for valid bearer/HMAC, 401 for invalid bearer, invalid HMAC, and stale replay, and 200/`duplicate=true` for an idempotent retry. Middleware -> n8n live evidence returned 200 for all governed endpoints and 403 for invalid auth. Automated timeout evidence proves five bounded attempts followed by `dead_letter`.

## Explicit delivery targets

| Target | Runtime address | Exposure |
|---|---|---|
| Odoo | `http://codestra-odoo-1:8069` | private Docker network |
| n8n | `http://codestra-n8n-1:5678` | private Docker network |
| Telnexa | `https://10.40.0.2/telnexa` | private vSwitch, simulator remains selected |
| Klyrow | `https://10.40.0.2/klyrow` | private vSwitch, safe/test remains selected |
| Kyqra | `http://kyqra:3100` | private service DNS contract, safe adapter selected |

## BLOCKED-EXTERNAL

- Production provider credentials/owner approval for real Telnexa, Klyrow, and Kyqra traffic are unavailable. Safe simulator/test integrations are PASS and production delivery remains authorization-gated.
- Public HTTPS on ports 80/443 and certificate lifecycle ownership remain outside this private control-plane change. No internal API was exposed publicly to satisfy testing.
- Remote `kyqra-deploy`, `telnexa-deploy`, and `klyrow-deploy` operating-system identities/authorized keys still require their server owner.
