# Middleware API Connectivity Audit Report

Audit date: 2026-08-15 UTC

Branch: `agent/middleware-n8n-control-plane`

Live evidence: `artifacts/connectivity-audit.json` (`20260815T130649Z-c629903b`)

Safety: no bulk SMS/email, carrier submission, real email delivery, production crawler job, direct Odoo PostgreSQL write, or destructive workflow/data action occurred.

## Outcome

The locally executable safe suite completed with **93 PASS / 0 FAIL**, and the repository suite completed with **194 tests plus 9 subtests PASS**. Telnexa simulator, Klyrow test mode, all inbound service identities, HMAC negative cases, replay/idempotency behavior, correlation lookup, private routes, health, metrics, and mTLS were observed live.

The Odoo functional follow-up is complete: both Odoo directions now have dedicated credentials, live authenticated business-path evidence, replay/idempotency enforcement, correlation/audit evidence, and bounded retry evidence. The broader platform remains **NO-GO for production integration activation** because public HTTPS is unreachable, n8n functional wiring is not activated, Kyqra egress/worker is absent, and three remote deployment identities do not exist.

## Required matrix

| Integration | Direction | Network | Auth | Functional | Idempotency | Retry/DLQ | Overall |
|---|---|---|---|---|---|---|---|
| Odoo | Middleware -> Odoo | PASS: `/web/health` 200 and private API live | PASS: dedicated user 59 + HMAC | PASS: tagged contact create/read/update, activity, status | PASS: duplicate suppressed; exact replay 409 | PASS: isolated 5-attempt exhaustion to DLQ | PASS |
| Odoo | Odoo -> Middleware | PASS: `/health` 200 from Odoo | PASS: dedicated bearer + HMAC | PASS: live signed `customer.updated` returned 202 | PASS: exact replay 409; fresh-event retry duplicate 200 | PASS: middleware bounded delivery policy | PASS |
| n8n | Middleware -> n8n | PASS: `/healthz` 200 | FAIL: no target credential/wiring | BLOCKED | N/A | N/A | BLOCKED |
| n8n | n8n -> Middleware | PASS: `/health` 200 from n8n | FAIL: no credential/webhook | BLOCKED: zero active webhooks | PASS: server-side n8n identity test | N/A | BLOCKED |
| Telnexa | Middleware -> Telnexa | PASS: local simulator | PASS: simulator safety gate | PASS: `simulator_accepted`, no carrier submit | PASS: same message read back | PASS: isolated retry/circuit suite | PASS (simulator scope) |
| Telnexa | Telnexa -> Middleware | PASS: control-plane and private gateway | PASS: live bearer/HMAC | PASS: signed DLR and all private routes | PASS: replay rejected | N/A on successful callback | PASS |
| Klyrow | Middleware -> Klyrow | PASS: local test adapter | PASS: test-mode safety gate | PASS: `test_accepted`, `.invalid` recipient | PASS: same message read back | PASS: isolated retry/circuit suite | PASS (test scope) |
| Klyrow | Klyrow -> Middleware | PASS: control-plane and private gateway | PASS: live bearer/HMAC | PASS: delivered event and all private routes | PASS: replay rejected | N/A on successful callback | PASS |
| Kyqra | Middleware -> Kyqra | FAIL: no live Kyqra service endpoint | BLOCKED: no deployed egress credential | PASS source safe-job contract; FAIL live worker | PASS source | N/A | BLOCKED |
| Kyqra | Kyqra -> Middleware | PASS: private ingress | PASS: live bearer/HMAC | PASS: jobs/results/progress/failures | PASS: replay/entity duplicate protection | N/A on successful callback | PASS |

## Evidence and controls

| Area | Result | Evidence / remaining action |
|---|---|---|
| Service identities | PARTIAL | `codestra-vicidial` PASS. `kyqra-deploy`, `telnexa-deploy`, `klyrow-deploy` BLOCKED because accounts/authorized keys are absent on `10.40.0.2`. |
| Private vSwitch | PASS | VLAN 4001, MTU 1400, ARP live; private TCP 22/8443 live. Peer intentionally blocks ICMP. |
| Private port exposure | PASS | 8095 exact-source UFW; 8096/NATS loopback; Redis/PostgreSQL/Odoo/n8n Docker-private; public probes blocked. |
| Public ingress | FAIL | DNS points to this host, but ports 80/443 refuse connections and HTTPS checks are unreachable. |
| TLS/mTLS | PARTIAL | Remote adapter mTLS health/readiness 200 and missing-client rejection observed. Certificates valid; private renewal automation not observed. Public TLS unavailable. |
| HMAC | PASS | Valid/invalid/stale signatures live-tested for all five control-plane identities and all three private-gateway identities. |
| Replay protection | PASS | Odoo event-ID reuse is rejected with 409 in both directions. A fresh event ID with the same idempotency key remains a safe retry. Private gateway also rejects event-ID replay. |
| Idempotency | PASS for tested endpoints | Odoo contact/status and Odoo event retries suppressed duplicate effects; SMS/email repeated requests returned the same message. Real crawler records remain BLOCKED. |
| Retry/DLQ | PASS for Odoo / PARTIAL platform-wide | An isolated unreachable Odoo endpoint reached DLQ after exactly 5 attempts. No production dependency was disrupted. Other production restart/failure exhaustion remains BLOCKED-SAFETY. |
| Circuit breaker | PASS in tests / BLOCKED live outage | Threshold 3, cooldown 30 seconds, half-open recovery tested in suite. No real dependency was taken down. |
| Correlation ID | PASS locally | Odoo contact responses, middleware ledger entries, and Odoo outbound results preserved their correlation IDs; prior cross-provider evidence remains valid. |
| Odoo integrity | PASS | No direct application Odoo PostgreSQL connection/write found. Read-only audit query only. |
| n8n governance | FAIL activation | 20 workflows, all inactive; zero webhooks and credentials. No hard-coded production credential was found. |
| Health/readiness | PASS locally | Control plane, gateway, Odoo, n8n, Redis, PostgreSQL, containers, and remote adapter healthy. No local Jasmin/Mautic/Postal/Kyqra process exists. |
| Monitoring | PASS for deployed targets | Prometheus reported 28/28 active targets UP, including middleware quarantine probes, Odoo, PostgreSQL, Redis, containers, node, TLS/HTTPS probes. Provider-specific Kyqra/Klyrow/Telnexa business metrics are absent. |
| Queues | PARTIAL | SQLite delivery queues, Redis, NATS JetStream, and DLQ contracts observed. No RabbitMQ. Live production restart survival not forced. |
| DNS | PARTIAL | `crm`, `api`, `n8n`, `auth.codestra.agency` resolve correctly to `65.109.65.169`; HTTPS is unreachable. No active `10.40.0.3` use was introduced. |

## Repairs completed

1. Pulled branch head `b0902d5` before auditing.
2. Repaired the stale `10.40.0.2` known-host entry only after matching its ED25519 fingerprint to the independently pinned public endpoint; retained a backup.
3. Added a repeatable, secret-redacting safe audit harness covering the live control plane and every legacy private-gateway route.
4. Integrated the concurrent safe Kyqra job API repair: private/test-only target policy, fail-closed production authorization, idempotency/correlation persistence, OpenAPI, and tests. It is source-validated but not claimed live until deployed with an approved Kyqra worker.
5. Added the required inventory, endpoint, service identity, network, TLS, system-specific, testing, retry/DLQ, and deployment documentation.
6. Added and deployed `codestra_middleware_bridge`, a synthetic-only Odoo ORM API with a dedicated least-privilege service identity, immutable idempotency evidence, and Odoo audit events.
7. Configured distinct Odoo-direction credentials outside Git and wired the discovered Docker-private endpoints.
8. Hardened Odoo ingress so exact signed event-ID reuse is rejected while legitimate fresh-event idempotent retries remain safe.

No safe local change can invent remote Kyqra/Klyrow/Telnexa accounts or services, activate n8n production workflows, restore public ingress, or establish certificate lifecycle ownership without external intent/credentials. Those actions require the owners identified above. Odoo is no longer among the blocked integrations.
