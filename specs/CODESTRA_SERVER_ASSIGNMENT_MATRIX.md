# Codestra Server Assignment Matrix

## Server A — Application and Orchestration Control Plane

Server A: `65.109.65.169` / `10.40.0.1`

Place on Server A:

- Odoo 19
- middleware
- PostgreSQL
- Redis
- Keycloak
- NATS JetStream
- Temporal
- n8n staging queue mode
- AI Gateway
- AI provider routing
- AI prompt/model registries
- AI tool broker
- AI knowledge service
- AI review and evaluation
- Webhook Gateway
- outbound webhook delivery
- WebSocket Gateway
- reporting and analytics
- deterministic metric library
- agent, team, supervisor, department, campaign, and business-unit scoring
- automation registry
- event catalog
- rules engine
- SLA engine
- customer journey
- consent and preference center
- communication policy
- template management
- data-quality service
- simulation and dry-run
- appointment models and reminder orchestration
- IVR menu policy and customer/appointment lookup
- callback business records and orchestration
- provisioning orchestration
- feature-flag registry
- unified audit
- release approval gates
- object-storage integration
- secrets-manager integration
- observability
- final evidence and cross-server acceptance

Server A must not directly modify VICIdial or Asterisk.

---

## Server B — Telephony and Adapter Plane

Server B: `65.21.67.207` / `10.40.0.2`

Place on Server B:

- VICIdial
- Asterisk
- Apache
- MariaDB telephony truth
- reporting adapter
- reporting snapshot adapter
- telephony event gateway
- IVR execution adapter
- queue adapter
- callback publication adapter
- APPT_PREP pause/resume adapter
- VICIdial agent provisioning adapter
- Asterisk/WebRTC endpoint provisioning adapter
- offboarding and revocation adapter
- recording-reference service
- read-back verification
- private health/readiness/metrics
- bounded local event spool
- event publisher or middleware client
- synthetic telephony fixtures
- Asterisk and database query safety
- adapter rollback

Server B must not deploy NATS JetStream, Temporal, Odoo, Keycloak, n8n, or a competing AI platform.

---

## Shared Cross-Server Responsibilities

Server A is the governance owner; both servers implement their side.

Shared responsibilities:

- canonical API and event contracts
- mTLS identities
- service authorization
- environment/business-unit/campaign validation
- correlation IDs
- idempotency
- replay protection
- audit
- feature flags
- synthetic test campaigns
- cross-server reporting acceptance
- appointment APPT_PREP acceptance
- IVR and callback acceptance
- provisioning and offboarding acceptance
- AI transcript and review acceptance
- WebSocket acceptance
- reconciliation
- performance testing
- security testing
- rollback rehearsal
- evidence checksums
- final go/no-go package

---

## Core Rule

- Business and automation logic: Server A
- Telephony execution and telephony truth: Server B
- Durable events: NATS on Server A
- Long-running business workflows: Temporal on Server A
- External automation and notifications: n8n on Server A
- Live Asterisk/VICIdial actions: Server B adapter
- Every Server B action: requested by Server A and confirmed by Server B read-back
- Production activation: separate formal approval
