# Middleware/n8n control-plane deployment report

## Unified communications extension — 2026-08-15

The loopback-only image now includes the SMS/email ledger, safe provider adapters, identity/preferences/suppression state, metering, message timelines, retry/circuit controls, and tenant APIs. SQLite initialization is additive and needs no destructive migration. Compose retains its named persistent volume, read-only filesystem, least privilege, health check, and `127.0.0.1:8096` binding.

Validation uses Telnexa simulator and Klyrow test mode; no real destination was contacted. Production deployment was not performed because provider credentials, authorized destinations, deliverability gates, and explicit authorization are absent. Before a future rollout, back up the volume and environment, deploy the exact commit SHA, validate Compose/build, verify health/readiness, run synthetic idempotency and restart persistence, and retain the prior image/volume backup for rollback.

P0 was implemented additively on 2026-08-15. The existing `10.40.0.1:8095` private ingress, Odoo integration containers, n8n production/staging workflows, NATS JetStream, firewall, mTLS ingress, and databases were inventoried and preserved. The control plane binds only to `127.0.0.1:8096`; authenticated Odoo/n8n delivery is enabled only on the private service network.

Implemented: independent identities, HMAC/replay verification, v1 event contract, tenant/idempotency enforcement, queue/retry/DLQ state, correlation history, central consent preferences, RBAC operations summary/actions, immutable-style audit rows, integration pause/resume, circuit state/metrics, governed n8n exports (inactive in Git and acceptance-published at runtime), Docker deployment, backup/DR documentation, and automated security/control tests.

Validation: the original deployment passed 7 focused tests and 175 tests plus 9 subtests. The unified communications extension passes 191 tests plus 9 subtests, Compose/OpenAPI parsing, Python compilation, image build, live loopback API smoke, and the repository secret audit. No real SMS or email was sent. The original ingress remained healthy throughout.

Odoo/n8n endpoint credentials and workflow activation are complete for the private non-production control-plane scope. Direct private checks to external Kyqra (`10.40.0.2:3100`) and Klyrow (`10.40.0.2:18000`) timed out during the earlier baseline; Telnexa private HTTPS correctly requested its client certificate. Real provider availability/mTLS still requires provider credentials and owner approval. No real SMS or email was sent.
# Connectivity audit deployment addendum — 2026-08-15

- Source branch was fast-forwarded to remote commit `b0902d5` before work.
- No production container image, compose stack, database, workflow, or firewall policy was redeployed.
- One local operational repair updated the stale `10.40.0.2` SSH host-key cache after independent fingerprint equality proof; backup retained.
- New audit scripts execute against current containers in safe mode and produced 93/93 PASS evidence without provider delivery.
- Repository validation passed after integrating the concurrent safe Kyqra job repair: 192 tests and 9 subtests.
- Non-production control-plane activation is PASS. Real provider activation remains **NO-GO** until provider credentials/approval, remote service accounts, and private certificate renewal ownership are resolved.

# Control-plane integration activation addendum — 2026-08-15

The locally controlled gaps above are now closed. Separate Odoo and n8n credentials were generated into `/etc/codestra/secrets/control-plane.env` (mode 0600), never written to Git, and provisioned through supported Odoo/n8n service interfaces. Odoo and n8n use the discovered private container ports 8069 and 5678. Control-plane API exposure remains loopback-only; internal service traffic remains on `codestra_edge`.

Thirteen governed event workflows plus the common error workflow were imported and published. The Odoo approved HMAC controller was repaired for the installed event-model schema. The worker now authenticates/signs both targets, preserves correlation/idempotency headers, performs bounded retry/DLQ handling, and updates the shared circuit breaker. The Kyqra adapter now implements create, status, results, cancel, and retry without Redis/database bypass.

Final validation: 93/93 safe live audit checks PASS; 196 tests and 9 subtests PASS; all 18 target deliveries under `final-pass-0121173014` were read back as delivered with zero retries. Odoo contact CRUD/activity, Odoo -> Middleware, n8n -> Middleware, all required Middleware -> n8n webhooks, and safe Kyqra job control passed live. No real SMS, bulk email, or production crawl was submitted.

Deployment status is PASS for the non-production control-plane scope. Production provider activation remains BLOCKED-EXTERNAL pending separate provider credentials/approval, public TLS ownership, and remote deployment accounts.

# TLS/mTLS lifecycle automation addendum — 2026-08-15

All eight public endpoints were inventoried from their served certificates. They use valid Let's Encrypt leaves, terminate on the Caddy reverse proxy, and are automatically renewed/hot-reloaded by Caddy. The independent six-hour hostname/expiry monitor remains the safe external renewal check.

Middleware-owned private roots and leaves were inventoried without printing or committing key material. Daily leaf renewal automation now has explicit subjects/SANs, issuer paths, renewal windows, scoped reload targets, owner assignments, overlap backups, rollback behavior, expiry metrics, and warning/critical alerts. The current private CA is deliberately preserved. Safe forced dry-run issuance validates the full signing path without changing deployed material.

The Codestra Provisioning Staging CA and its server leaf expire on 2026-08-25. They are monitor-only and require an approved dual-root CA rotation; automation intentionally refuses to replace that CA. This is a critical staging PKI action but does not invalidate the separately verified middleware↔VICIdial private ingress.

Verification passed: all five renewable private profiles completed forced safe dry-run issuance with no deployed changes; the lifecycle and public-monitor timers are enabled with future triggers; the first lifecycle service run exited successfully; Prometheus accepted three lifecycle rules; all eight public leaf/hostname checks passed; the reverse proxy restarted and recovered health; private ingress rejected a missing client certificate and accepted the approved client certificate before applying route authorization. Repository validation passed 198 tests and 9 subtests.

## Final provider readiness after identity/TLS remediation — 2026-08-15

The stale deployment-account blocker is closed. All three dedicated deployment identities authenticate to `37.27.128.39`, and four mismatched user/key combinations are explicitly rejected with `IdentitiesOnly=yes`. The three SSH aliases were repaired locally from the non-listening private target to the already verified public transport; no working key was replaced. The accounts remain least-privilege: no unrestricted sudo and no Docker-socket membership, with fixed read-only/status wrappers for the owned stack.

Live inventory confirms the real provider software boundaries. Kyqra has healthy API, HTTP/Playwright/callback workers, Redis and PostgreSQL; Telnexa has healthy Jasmin, RabbitMQ, Redis and PostgreSQL; Klyrow has healthy gateway, Mautic, Postal, queues, databases and monitoring. Databases/queues are internal, management endpoints are loopback/private, and public exposure remains limited to SSH and Nginx HTTP/TLS. The intended Kyqra, Telnexa and Klyrow certificates validate and expire in November 2026; Certbot dry-run renewal, reload hooks and certificate monitoring were previously proven.

The fresh middleware safe audit `20260815T142830Z-a1037f76` passed 93/93 and the repository suite passed 198 tests plus 9 subtests. Safe signed reverse tests for Kyqra jobs/results and Telnexa inbound/DLR passed authentication, HMAC, replay and deduplication controls. Klyrow remains in safe mode and no real email was submitted. Unrestricted production delivery remains disabled.

Final dispositions:

- Telnexa — **READY-FOR-PROVIDER**: software, isolation, public TLS, Jasmin health, simulator route and billing safety are ready. Real SMPP credentials/configuration and owner approval are still required before any carrier bind or billable SMS.
- Klyrow — **BLOCKED-EXTERNAL**: application infrastructure and web TLS are ready, but `mail.klyrow.com`, MX, SPF, published Postal DKIM, matching PTR, SMTP TLS/STARTTLS and owner approval remain absent.
- Kyqra — **BLOCKED-EXTERNAL**: the real crawler stack is healthy, but middleware lacks an accepted outbound Kyqra API credential and cannot currently reach private port 3100. The real worker-backed callback through middleware to n8n/Odoo was therefore not claimed; provider-owner credential distribution/private-path repair and approval are required.

No real SMS, bulk email, unrestricted crawl, provider activation, database exposure, server-key replacement, or production-gate change occurred.
