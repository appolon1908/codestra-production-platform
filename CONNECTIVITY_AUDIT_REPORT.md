# Middleware API Connectivity Audit Report

Final validation: 2026-08-15 UTC
Branch: `agent/middleware-n8n-control-plane`
Safe audit evidence: `artifacts/connectivity-audit-mission6-20260815.json` (`20260815T140518Z-5c1e9899`, 93 PASS / 0 FAIL)
Repository validation: 198 tests and 9 subtests PASS.
Secret validation: Gitleaks 8.30.1 scanned 157 commits with no leaks.
Fresh Odoo functional evidence: `artifacts/odoo-middleware-functional-20260815T140709Z.json`.

Mission 2 was revalidated live at 2026-08-15 14:08 UTC. A fresh safe audit (`20260815T140813Z-b2579672`) passed 93/93 with zero failures, and the focused n8n/control-plane suite passed 14/14. A direct runtime export showed 34 workflows: only the 13 required governed event workflows and the common error workflow were active; all 20 unrelated pre-existing workflows remained inactive. The two external secret files remained root-owned mode 0600 with the required n8n identity variables configured; no secret value was printed or committed.

Mission 3 deployed the approved crawler-job adapter to the live control-plane API and worker. Safe job `5fb4cb66-dabf-4951-a800-34a17d5dfe52` passed create, duplicate replay, status, one-result read-back, cancel, retry, invalid credential, signed callback, normalization, and Odoo/n8n fan-out under correlation `kyqra-m3-6a778644ac`. Odoo delivered with zero retries; n8n recovered from an open circuit after the configured 30-second cooldown and delivered on bounded attempt four. The post-deployment safe audit `20260815T141335Z-ec272b7e` passed 93/93, and the repository suite passed 198 tests plus 9 subtests. This is live middleware evidence, not live Kyqra worker evidence: the provider ID remained `test-job-*`, no Kyqra/Crawlee/Playwright service was present, and the discovered `10.40.0.2:3100` endpoint timed out. The full provider-worker lifecycle is therefore **BLOCKED-EXTERNAL**.

## Final provider-readiness reconciliation — 2026-08-15 14:30 UTC

This section supersedes the earlier SSH-blocked provider assessment. The dedicated `kyqra-deploy`, `telnexa-deploy`, and `klyrow-deploy` identities all authenticated with `BatchMode=yes` and returned the expected user and host. The aliases incorrectly targeted private `10.40.0.2:22`, while direct authentication with the same keys succeeded at the verified public host `37.27.128.39`; only the three local alias `HostName` values were repaired. Server keys and authorized keys were not replaced. Four explicit wrong user/key tests with `IdentitiesOnly=yes` returned `Permission denied (publickey,password)`.

The provider host intermittently rate-limits/refuses rapid new SSH connections. Those transport refusals were not counted as authentication-negative evidence; each negative was repeated after the listener recovered until the server explicitly rejected the wrong public key.

| System | Software/infrastructure readiness | Provider credential readiness | DNS/PTR readiness | Owner approval | Final status |
|---|---|---|---|---|---|
| Telnexa | Live Jasmin 0.11.0, RabbitMQ, Redis, and PostgreSQL containers are healthy. Jasmin HTTP, jCli, and SMPP are loopback-only; the backend Docker network is internal and a separate egress network exists. Public `sms.telnexa.co`, `api.telnexa.co`, and `status.telnexa.co` certificates verify through 2026-11-13. The simulator route has bounded cleanup, rate `0`, and no carrier submission; current safe middleware ingress/DLR tests pass. | Real SMPP host/system ID/password/bind/TON/NPI/throughput and MO/DLR callback configuration are absent; only the provider placeholder exists and no live connector/MT route is present. | Required public service TLS is ready. Carrier DNS belongs to the selected provider and is not yet applicable. | Required before any real connector, destination, or billable submission. | **READY-FOR-PROVIDER** |
| Klyrow | Live gateway, Mautic web/cron/worker, Postal web/worker/SMTP, RabbitMQ, PostgreSQL/MariaDB, and monitoring containers are healthy. The private gateway and loopback-only Postal SMTP boundaries are intact. Six Klyrow web certificates verify through 2026-11-13. `GET /v1/health` returns `safe_mode=true` and `production_gate_approved=false`; invalid middleware auth is rejected. | Klyrow middleware credentials exist, but production SMTP remains intentionally disabled. No bulk email was sent. | **Current blocker:** `mail.klyrow.com`, MX, SPF, Postal DKIM publication, matching PTR, SMTP certificate, and STARTTLS are absent. DMARC exists with quarantine policy. | Required after DNS/deliverability and controlled seed tests. | **BLOCKED-EXTERNAL** |
| Kyqra | Live API, HTTP worker, Playwright browser worker, callback worker, Redis, and PostgreSQL containers are running; API/Redis/PostgreSQL health is 200 and unauthenticated API access is 401. Public `crawler.kyqra.com` TLS verifies through 2026-11-13. Middleware's safe adapter lifecycle and downstream n8n/Odoo controls remain validated. | **Current blocker:** middleware has no `KYQRA_OUTBOUND_API_KEY`; its configured inbound key is correctly rejected by the real Kyqra API. The private `10.40.0.2:3100` path also times out despite the provider-side listener/rule inventory. The approved real job therefore could not be created and no real-worker callback/fan-out is claimed. | `crawler.kyqra.com` A/TLS is ready; no PTR dependency applies to crawling. | Provider owner must distribute the API credential, restore the private path, approve the harmless target, and authorize the callback test. | **BLOCKED-EXTERNAL** |

Current middleware validation remains fail-closed: `TELNEXA_MODE=simulator`, `KLYROW_MODE=test`, `KYQRA_MODE=test`, and unrestricted production delivery is not authorized. A fresh safe audit `20260815T142830Z-a1037f76` passed 93/93; the repository suite passed 198 tests and 9 subtests. The reverse Kyqra/Telnexa signed gateway matrix passed valid authentication, HMAC, replay, entity deduplication, inbound, and DLR checks. No real SMS, bulk email, unrestricted crawl, direct database write, or provider activation occurred.

## Outcome

Every locally repairable integration path is PASS in the non-production scope. The live private stack now has separate Odoo and n8n service identities, signed inbound requests, authenticated outbound delivery, 13 required event workflows plus one common error workflow, explicit private delivery targets, and the complete Kyqra job-control adapter. No real SMS, bulk email, production crawl, direct database write, or unrelated production-record mutation occurred.

Live correlation `final-pass-0121173014` delivered all required Telnexa, Klyrow, Kyqra, and customer events to their applicable Odoo and n8n targets with zero retries. Odoo JSON-RPC evidence created/read/updated tagged partner `CODESTRA_CONNECTIVITY_TEST_e6bc729f65` and activity 15 through the dedicated service user. Odoo -> Middleware returned 202 under correlation `odoo-live-232958819a9044ce8aa2d347276bf030`; n8n -> Middleware returned 202 under correlation `n8n-live-5148cef9-4b4b-4310-85cc-1b665d22d725`. Kyqra safe job `c6957821-7e9a-4a49-949b-bfac23e64165` passed create, duplicate replay, status, results, cancel, retry, and invalid-auth tests.

The Odoo functional follow-up additionally exercised the dedicated ORM bridge: tagged contact create/read/update, activity and status changes, correlation/audit persistence, invalid authentication, exact event-ID replay rejection, fresh-event idempotent retry, and isolated five-attempt DLQ exhaustion all passed live.

The `2026-08-15T14:07:09Z` rerun created only synthetic partner 115 and activity
17, then left the partner inactive. Middleware -> Odoo returned
`201/200/200/201/200` for create/read/update/activity/status, `200` for the
idempotent retry, `409` for event replay, and `401` for invalid HMAC. Odoo ->
Middleware returned `202`, `200`, `409`, `401`, and `401` for acceptance,
idempotent retry, replay, invalid bearer, and invalid HMAC respectively. ORM
read-back confirmed the exact tenant, correlation records, six events, and six
audit rows without a direct PostgreSQL write.

## Final matrix

`PASS` is based on live execution plus read-back, not configuration presence. Private Docker HTTP is marked PASS where it is an intentionally isolated same-host network boundary; public exposure was not added.

| Flow | NETWORK | AUTH | TLS/mTLS | HMAC | REPLAY | IDEMPOTENCY | CORRELATION ID | RETRY | DLQ | CIRCUIT BREAKER | TENANT ISOLATION | AUDIT LOG | ODOO RESULT | FINAL STATUS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. Telnexa simulator -> Middleware -> n8n -> Odoo | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 2. Odoo/n8n -> Middleware -> Telnexa -> Jasmin simulator -> DLR -> Middleware -> n8n -> Odoo | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 3. Odoo/n8n -> Middleware -> Klyrow test -> delivery/bounce -> Middleware -> n8n -> Odoo | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| 4. Odoo/n8n -> Middleware -> Kyqra safe crawler -> Middleware -> n8n -> Odoo | BLOCKED-EXTERNAL | BLOCKED-EXTERNAL | BLOCKED-EXTERNAL | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | BLOCKED-EXTERNAL |

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
| Kyqra | `http://10.40.0.2:3100` | discovered private configuration; endpoint currently unreachable |

## BLOCKED-EXTERNAL

- Telnexa carrier SMPP credentials/configuration and explicit owner approval remain external; its software is **READY-FOR-PROVIDER** and no billable route exists.
- Klyrow mail DNS, MX, SPF, published Postal DKIM, provider PTR, SMTP TLS/STARTTLS, controlled seed validation, and owner approval remain external.
- Kyqra's API/workers are deployed and healthy, but its owner must distribute a dedicated outbound middleware credential and restore/confirm private `10.40.0.2:3100` reachability before the real worker callback path can pass.
- Deployment identities and intended public TLS names are no longer blockers. Unrestricted provider traffic remains disabled.
