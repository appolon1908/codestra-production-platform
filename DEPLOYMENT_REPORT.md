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

## Final provider activation readiness — 2026-08-15

A refreshed live safe audit produced 93 PASS / 0 FAIL (`20260815T140234Z-f5355911`), and the focused unit suite produced 59 PASS. Telnexa remained in simulator mode, Klyrow and Kyqra remained in test mode, and the independent production-delivery authorization gate remained unset.

Final dispositions are Telnexa **BLOCKED-EXTERNAL**, Klyrow **BLOCKED-EXTERNAL**, and Kyqra **BLOCKED-EXTERNAL**. Their distinct deployment keys exist and are correctly permissioned, but all three deployment accounts rejected public-key authentication. Read-only inspection through the approved peer administrator found no observable provider application runtimes beyond the existing restricted adapter. Jasmin/SMPP routes and DLR/MO, Postal/Mautic and mail DNS/PTR/TLS, and the real Kyqra worker/API and target-policy enforcement therefore lack live provider-side proof.

The non-production paths remain PASS-SAFE evidence, not provider readiness: simulator SMS and synthetic DLR, test email and synthetic delivery, and a bounded safe Kyqra job traversed middleware and the governed n8n/Odoo targets with reverse signed ingress. No real SMS, bulk campaign, SMTP delivery, production crawl, provider activation, firewall change, or provider secret change occurred.
