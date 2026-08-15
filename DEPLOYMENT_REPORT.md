# Middleware/n8n control-plane deployment report

## Unified communications extension — 2026-08-15

The loopback-only image now includes the SMS/email ledger, safe provider adapters, identity/preferences/suppression state, metering, message timelines, retry/circuit controls, and tenant APIs. SQLite initialization is additive and needs no destructive migration. Compose retains its named persistent volume, read-only filesystem, least privilege, health check, and `127.0.0.1:8096` binding.

Validation uses Telnexa simulator and Klyrow test mode; no real destination was contacted. Production deployment was not performed because provider credentials, authorized destinations, deliverability gates, and explicit authorization are absent. Before a future rollout, back up the volume and environment, deploy the exact commit SHA, validate Compose/build, verify health/readiness, run synthetic idempotency and restart persistence, and retain the prior image/volume backup for rollback.

P0 was implemented additively on 2026-08-15. The existing `10.40.0.1:8095` private ingress, Odoo integration containers, n8n production/staging workflows, NATS JetStream, firewall, mTLS ingress, and databases were inventoried and preserved. The new control plane binds only to `127.0.0.1:8096`; outbound Odoo/n8n delivery is false.

Implemented: independent identities, HMAC/replay verification, v1 event contract, tenant/idempotency enforcement, queue/retry/DLQ state, correlation history, central consent preferences, RBAC operations summary/actions, immutable-style audit rows, integration pause/resume, circuit state/metrics, governed inactive n8n catalog, Docker deployment, backup/DR documentation, and automated security/control tests.

Validation: the original deployment passed 7 focused tests and 175 tests plus 9 subtests. The unified communications extension passes 191 tests plus 9 subtests, Compose/OpenAPI parsing, Python compilation, image build, live loopback API smoke, and the repository secret audit. No real SMS or email was sent. The original ingress remained healthy throughout.

Production activation remains gated on approved Odoo/n8n endpoint credentials and workflow owner activation. Direct private checks to Kyqra (`10.40.0.2:3100`) and Klyrow (`10.40.0.2:18000`) timed out during final validation; Telnexa private HTTPS correctly requested its client certificate. These peer availability/mTLS checks require their approved credentials/owners and do not justify weakening ingress. No real SMS or email was sent. Public DNS/provider changes were not required for this loopback-only component.
