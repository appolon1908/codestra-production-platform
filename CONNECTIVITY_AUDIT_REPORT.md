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
| Kyqra | Live API, HTTP worker, Playwright browser worker, callback worker, Redis, and PostgreSQL are healthy. The API is available on loopback and the dedicated private address `10.40.0.4:3100`; UFW permits only middleware `10.40.0.1` to the private listener. Workers, Redis, and PostgreSQL have no published host ports. One bounded `https://example.com/` job completed through the real HTTP worker and callback worker. | A dedicated middleware outbound API credential is installed in root-owned runtime secret storage and accepted by Kyqra; an invalid bearer returns 401. No credential is embedded in Git. | `crawler.kyqra.com` A/TLS is ready; no PTR dependency applies to crawling. | Approval was limited to the harmless single-page proof. Unrestricted crawling remains disabled and still requires owner authorization. | **PASS-SAFE** |

Current middleware validation remains fail-closed: `TELNEXA_MODE=simulator`, `KLYROW_MODE=test`, and Kyqra uses the narrow `private_safe` mode with `example.com` as its sole configured target. Unrestricted production delivery is not authorized. No real SMS, bulk email, unrestricted crawl, direct database write, or provider activation occurred.

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
| Kyqra | `http://10.40.0.4:3100/api/v1/jobs` | private vSwitch; UFW source-restricted to `10.40.0.1`; API only |

## BLOCKED-EXTERNAL

- Telnexa carrier SMPP credentials/configuration and explicit owner approval remain external; its software is **READY-FOR-PROVIDER** and no billable route exists.
- Klyrow mail DNS, MX, SPF, published Postal DKIM, provider PTR, SMTP TLS/STARTTLS, controlled seed validation, and owner approval remain external.
- Kyqra has no remaining connectivity blocker in the approved safe scope. Unrestricted targets or production crawling still require explicit owner authorization.
- Deployment identities and intended public TLS names are no longer blockers. Unrestricted provider traffic remains disabled.

## Kyqra private API completion — 2026-08-15 15:03 UTC

The earlier Kyqra blocker is superseded by current live evidence. Runtime inspection found that the API container listens on port 3000 and was published as host port 3100; port 3100 was therefore retained rather than invented. The old private address `10.40.0.2` was occupied by a different MAC on the vSwitch. Kyqra now has the conflict-free secondary address `10.40.0.4`, persisted through netplan, and Docker publishes only the API at `10.40.0.4:3100` plus the pre-existing loopback binding. The stale `.2:3100` firewall allowance was removed. The sole private allowance is `10.40.0.1 -> 10.40.0.4:3100` on the vSwitch interface.

The API, HTTP worker, Playwright worker, callback worker, Redis, and PostgreSQL are healthy. HTTP/Playwright/callback workers publish no ports; Redis 6379 and PostgreSQL 5432 remain container-network-only. The dedicated outbound credential and URL are held only in root-owned mode-0600 runtime secret files outside Git. Valid authentication reached live API stats; invalid authentication returned 401.

Live job `5500be22-064b-41e9-bd20-145102047412` / provider job `6c247807-55ff-446a-bd6e-ce704d96e0f3`, correlation `kyqra-private-live-f9f3e3e2dca44ac0b01bb4ffa004e8b8`, used only `https://example.com/`, one page, depth zero, HTTP mode, and a bounded rate. Create returned 202; exact replay returned 200 with the same job; status changed `running -> completed`; results returned one normalized record; cancel returned 200/`cancelled`; retry returned 200/`accepted` and completed; result count remained one after retry. The provider callback produced `kyqra.record.created` and `kyqra.job.completed`. Both events were delivered to n8n and Odoo with zero retries, the correlation and tenant survived every hop, and middleware stored exactly one normalized crawler result. Kyqra is therefore **PASS-SAFE**. This does not authorize arbitrary targets or unrestricted provider traffic.
