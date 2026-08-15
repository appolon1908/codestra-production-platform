# Middleware API Connectivity Audit Report

Final validation: 2026-08-15 UTC
Branch: `agent/middleware-n8n-control-plane`
Safe audit evidence: `artifacts/connectivity-audit-mission6-20260815.json` (`20260815T140518Z-5c1e9899`, 93 PASS / 0 FAIL)
Repository validation: 198 tests and 9 subtests PASS.
Secret validation: Gitleaks 8.30.1 scanned 157 commits with no leaks.

## Final provider-activation readiness recheck — 2026-08-15 14:02 UTC

| System | Safe integration evidence | Missing live provider evidence | Final status |
|---|---|---|---|
| Telnexa | Simulator dispatch, DLR normalization, signed reverse ingress, and Odoo/n8n delivery passed without carrier submission | `telnexa-deploy` SSH is rejected; no live Jasmin process, SMPP bind/credentials/approval, route-table read-back, MO/DLR read-back, or provider-side billing proof | **BLOCKED-EXTERNAL** |
| Klyrow | Test dispatch, delivery normalization, signed reverse ingress, and Odoo/n8n delivery passed using `.invalid` addresses | `klyrow-deploy` SSH is rejected; no live Postal/Mautic process or SPF/DKIM/DMARC/PTR/TLS proof | **BLOCKED-EXTERNAL** |
| Kyqra | Safe create/status/results/cancel/retry and Odoo/n8n delivery passed for job `c6957821-7e9a-4a49-949b-bfac23e64165` | `kyqra-deploy` SSH is rejected; no independently reachable Crawlee/Playwright worker/API or approved-target-policy inspection | **BLOCKED-EXTERNAL** |

The refreshed safe audit is `artifacts/connectivity-audit-final-provider-20260815.json` (`20260815T140234Z-f5355911`, 93 PASS / 0 FAIL); the focused unit run passed 59/59. All six per-service API/HMAC values are present, length-valid, and pairwise distinct within their credential class, without printing their values. The three ED25519 SSH keys are mode 0600 and have distinct public fingerprints, but live `BatchMode` authentication failed for every deployment account, so key presence is not counted as readiness.

Runtime remained fail-closed: `TELNEXA_MODE=simulator`, `KLYROW_MODE=test`, `KYQRA_MODE=test`, and `CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED` is unset. The control-plane API, worker, and private gateway are non-privileged read-only-root containers on `codestra_edge`; Odoo and n8n use the intended edge/backend networks. Provider-side per-service containers, networks, and runtime-secret boundaries could not be verified through the rejected identities.

The already-approved `codestra-admin` identity connected to `10.40.0.2` and observed SSH, HTTPS, and the restricted adapter on 8443, but no observable Jasmin, Postal, Mautic, Kyqra, Crawlee, or Playwright runtime. No real SMS, SMTP campaign, provider activation, or uncontrolled crawl occurred. An audit-harness integration fix now expects immutable Odoo event replay to return 409 and uses only event types present in the governed n8n catalog.

## Outcome

Every locally repairable integration path is PASS in the non-production scope. The live private stack now has separate Odoo and n8n service identities, signed inbound requests, authenticated outbound delivery, 13 required event workflows plus one common error workflow, explicit private delivery targets, and the complete Kyqra job-control adapter. No real SMS, bulk email, production crawl, direct database write, or unrelated production-record mutation occurred.

Live correlation `final-pass-0121173014` delivered all required Telnexa, Klyrow, Kyqra, and customer events to their applicable Odoo and n8n targets with zero retries. Odoo JSON-RPC evidence created/read/updated tagged partner `CODESTRA_CONNECTIVITY_TEST_e6bc729f65` and activity 15 through the dedicated service user. Odoo -> Middleware returned 202 under correlation `odoo-live-232958819a9044ce8aa2d347276bf030`; n8n -> Middleware returned 202 under correlation `n8n-live-5148cef9-4b4b-4310-85cc-1b665d22d725`. Kyqra safe job `c6957821-7e9a-4a49-949b-bfac23e64165` passed create, duplicate replay, status, results, cancel, retry, and invalid-auth tests.

The Odoo functional follow-up additionally exercised the dedicated ORM bridge: tagged contact create/read/update, activity and status changes, correlation/audit persistence, invalid authentication, exact event-ID replay rejection, fresh-event idempotent retry, and isolated five-attempt DLQ exhaustion all passed live.

## Final matrix

`PASS` is based on live execution plus read-back, not configuration presence. Private Docker HTTP is marked PASS where it is an intentionally isolated same-host network boundary; public exposure was not added.

| Flow | NETWORK | AUTH | TLS/mTLS | HMAC | REPLAY | IDEMPOTENCY | CORRELATION ID | RETRY | DLQ | CIRCUIT BREAKER | TENANT ISOLATION | AUDIT LOG | ODOO RESULT | FINAL STATUS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. Telnexa simulator -> Middleware -> n8n -> Odoo | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 2. Odoo/n8n -> Middleware -> Telnexa -> Jasmin simulator -> DLR -> Middleware -> n8n -> Odoo | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 3. Odoo/n8n -> Middleware -> Klyrow test -> delivery/bounce -> Middleware -> n8n -> Odoo | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 4. Odoo/n8n -> Middleware -> Kyqra safe crawler -> Middleware -> n8n -> Odoo | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

Mission 6 used only reserved synthetic destinations, `.invalid` email data, provider simulator/test modes, and safe crawler targets. Telnexa returned `simulator_accepted`, Klyrow returned `test_accepted`, signed DLR/delivery/bounce/crawler callbacks were accepted with replay protection, and normalized results were read back. No real carrier SMS, bulk email, or production crawl was submitted.

## Live workflow evidence

- Odoo: dedicated active service user, HMAC event receiver fixed for the installed model schema, contact CRUD and activity creation read back live. Tagged records remain identifiable for controlled cleanup.
- n8n: all 13 required event workflows plus `CP-90-STANDARD-ERROR-V1` were imported with a credential reference and published. Every event webhook returned HTTP 200 for valid auth and duplicate replay while preserving correlation, tenant, and customer context. Invalid auth returned 403. The 20 unrelated workflows remain preserved and inactive. Endpoint details are in `docs/N8N_ODOO_CONNECTIVITY.md`.
- Telnexa: simulator outbound and signed inbound/DLR paths passed. No carrier submission occurred.
- Klyrow: safe/test outbound and signed delivered/bounced/unsubscribed paths passed. Only `.invalid`/tagged test data was used; no bulk delivery occurred.
- Kyqra: safe adapter passed create/status/results/cancel/retry, correlation/request/idempotency propagation, duplicate replay, and invalid auth. Results normalized once and were delivered to n8n and Odoo.
- Failure controls: n8n -> Middleware live evidence returned 202 for valid bearer/HMAC, 401 for invalid bearer, invalid HMAC, and stale replay, and 200/`duplicate=true` for an idempotent retry. Middleware -> n8n live evidence returned 200 for all governed endpoints and 403 for invalid auth; deployed worker correlation `live-worker-corr-d21d2d4fbbee4909b40c88fdb59464fe` was read back delivered with zero retries. Automated timeout evidence proves five bounded attempts followed by `dead_letter`.

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
