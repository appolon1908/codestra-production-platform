# Codex Mission — Top-Tier Middleware + n8n Integration Control Plane

You have full autonomy to evolve the middleware and n8n platform in `appolon1908-hue/codestra-production-platform` into a production-grade integration control plane connecting Odoo, n8n, Kyqra, Telnexa, and Klyrow.

## Environment

Middleware server:
- Public IP: `65.109.65.169`
- Private vSwitch IP: `10.40.0.1`

Shared application server:
- Public IP: `37.27.128.39`
- Private vSwitch IP: `10.40.0.2`
- Hosts Kyqra, Telnexa, and Klyrow

Primary systems:
- Odoo — CRM/ERP/business records
- n8n — automation/orchestration
- Middleware — security, contracts, eventing, state, retries, idempotency, tenant boundaries
- Kyqra — crawler/data platform
- Telnexa — SMS platform
- Klyrow — email platform

Use the private vSwitch for service-to-service traffic wherever practical.

Do not write directly to Odoo PostgreSQL from Kyqra, Telnexa, Klyrow, or n8n. All business writes must go through approved middleware/Odoo service APIs.

Do not stop at a few webhooks. Build a maintainable, observable, secure control plane.

## 1. Core architecture

Implement a layered architecture:

```text
External/internal product services
        │
        ▼
API Gateway / Service Authentication
        │
        ▼
Middleware Integration Core
        ├── Event bus
        ├── Contract validation
        ├── Idempotency
        ├── Tenant isolation
        ├── Rate limits
        ├── Secrets/credentials abstraction
        ├── Retry / DLQ
        ├── Audit logs
        ├── Circuit breakers
        ├── Correlation IDs
        └── Observability
        │
        ├──────────────► Odoo service/API layer
        │
        └──────────────► n8n orchestration layer
                             │
                             ├── Kyqra workflows
                             ├── Telnexa workflows
                             └── Klyrow workflows
```

Middleware owns correctness and security. n8n owns orchestration, not core authorization or data integrity.

## 2. Unified event model

Create a versioned event envelope for all systems.

Required envelope fields:
- `event_id`
- `event_type`
- `event_version`
- `occurred_at`
- `received_at`
- `source`
- `tenant_id`
- `customer_id` where applicable
- `correlation_id`
- `causation_id`
- `idempotency_key`
- `payload`
- `metadata`

Examples:
- `customer.created`
- `customer.updated`
- `kyqra.job.completed`
- `kyqra.record.created`
- `telnexa.sms.received`
- `telnexa.sms.delivered`
- `telnexa.sms.failed`
- `klyrow.email.sent`
- `klyrow.email.delivered`
- `klyrow.email.bounced`
- `klyrow.email.complained`
- `klyrow.email.unsubscribed`
- `workflow.failed`
- `workflow.completed`

Use JSON Schema or equivalent contract validation.

Reject malformed or unsupported event versions cleanly.

## 3. API gateway and service identities

Create separate service identities for:
- Kyqra
- Telnexa
- Klyrow
- n8n
- Odoo integration services

Use independent credentials and scopes.

Do not reuse one key across products.

Support:
- hashed API keys where practical
- key prefixes / safe display
- scopes
- rotation
- revocation
- expiration
- per-service rate limits
- source IP or mTLS restrictions where appropriate

Use HMAC-SHA256 signed webhooks and/or mTLS on private traffic where already available.

Existing private ingress/security controls must be preserved and extended carefully rather than replaced blindly.

## 4. Idempotency and replay protection

Every mutating integration path must be idempotent.

Store and enforce idempotency keys for:
- SMS sends
- email sends
- crawler result ingestion
- webhook events
- Odoo writes
- workflow starts

Duplicate events must not create duplicate Odoo records, duplicate sends, or duplicate billing actions.

Implement webhook replay protection with:
- timestamp tolerance
- event ID uniqueness
- signature verification
- constant-time compare

## 5. Durable event bus and queues

Use a durable queue/event bus appropriate to existing infrastructure.

Support:
- at-least-once delivery
- bounded retries
- exponential backoff
- delayed retry
- dead-letter queue
- manual replay
- poison-event quarantine
- queue depth metrics

Separate queues logically for:
- Kyqra
- Telnexa
- Klyrow
- Odoo updates
- n8n triggers
- outbound callbacks

Do not allow one noisy product to starve the others.

## 6. Circuit breakers and dependency protection

Add circuit breakers for:
- Odoo
- n8n
- Kyqra API
- Telnexa API
- Klyrow API

Track:
- success rate
- latency
- timeout rate
- error rate

Open circuits on unhealthy dependencies and queue/retry safely.

Do not cascade failures across the platform.

## 7. Correlation and traceability

Generate or preserve a `correlation_id` for every cross-system operation.

Example:

Odoo lead
→ middleware event
→ n8n workflow
→ Telnexa SMS
→ DLR
→ middleware
→ Odoo update

All steps must be traceable by one correlation ID.

Implement structured logging and searchable event history.

## 8. n8n governance

Treat n8n as managed production automation, not an ad hoc workflow playground.

Implement:
- dev/staging/prod workflow separation where practical
- workflow naming conventions
- workflow ownership metadata
- versioned workflow exports in Git
- deployment/release process
- reusable sub-workflows
- standardized error workflow
- secrets via n8n credentials/environment only
- execution retention policy
- manual approval for high-risk production workflows where appropriate
- rollback procedure

Do not place long-lived plaintext secrets in workflow JSON committed to Git.

## 9. n8n workflow catalog

Create and document production workflows for at least:

### Kyqra
- job completed → normalize/enrich → Odoo lead/contact update
- crawler failure → retry/alert
- high-value lead → sales workflow

### Telnexa
- inbound SMS → identify customer/contact → Odoo activity → optional n8n automation
- DLR delivered → update message record
- DLR failed → retry/escalation policy
- opt-out keyword handling → suppression/compliance update

### Klyrow
- hard bounce → update contact status
- complaint → suppress and notify
- unsubscribe → update preference state
- delivered/open/click events → engagement scoring
- campaign completed → reporting workflow

Each workflow must use middleware-validated events as input.

## 10. Odoo integration layer

Create a clear Odoo service adapter owned by middleware.

Support:
- contacts
- leads/opportunities
- activities
- messaging history
- campaign metadata
- SMS delivery state
- email delivery state
- crawler provenance
- consent/preferences

Use approved Odoo APIs/service layer.

Implement mapping tables rather than scattered field mappings inside n8n nodes.

Add schema/version documentation.

## 11. Consent and communication preferences

Create a central communication preference model used by Telnexa and Klyrow.

Track at minimum:
- tenant/customer
- contact
- channel: SMS/email
- status
- source
- consent timestamp
- unsubscribe/opt-out timestamp
- reason/source event

Before outbound marketing sends, middleware must expose a preference check.

Do not allow workflows to bypass suppression/opt-out rules.

## 12. Middleware Operations Console

Build a protected operations dashboard.

Required views:
- overall platform health
- Odoo connectivity
- n8n connectivity
- Kyqra health
- Telnexa health
- Klyrow health
- event throughput
- queue depth
- failed events
- retrying events
- DLQ
- webhook deliveries
- workflow executions
- API error rate
- tenant/service usage
- circuit breaker state
- audit logs

Required actions with RBAC:
- replay event
- retry callback
- pause integration
- resume integration
- rotate service credential metadata/workflow
- drain queue safely
- inspect correlation timeline

Every privileged action must be audited.

## 13. RBAC and tenant isolation

Implement roles such as:
- platform_admin
- operations
- support
- auditor/read_only
- tenant_admin where applicable

Enforce authorization server-side.

Tenant A must never access Tenant B data, events, API keys, workflow status, or message history.

Add automated cross-tenant tests.

## 14. Secrets and credential management

Centralize secret handling.

Use environment/runtime secret storage and n8n credential storage.

Do not commit:
- API keys
- webhook secrets
- SMTP passwords
- SMPP passwords
- OAuth secrets
- database passwords
- private keys

Document secret rotation for each connected service.

## 15. Private networking and mTLS

Prefer private communication:
- middleware `10.40.0.1`
- shared services `10.40.0.2`

Preserve existing private HTTPS/mTLS infrastructure where already deployed.

Bind private APIs to private interfaces where practical.

Use narrow firewall rules.

Do not expose Redis, PostgreSQL, RabbitMQ, Docker socket, n8n internals, or middleware admin ports publicly.

Add free trusted TLS certificates with automatic renewal to all public middleware/n8n web interfaces where DNS permits.

Use Let's Encrypt/ACME, renewal hooks, expiry monitoring, and safe reloads.

SSH remains key-based and separate from TLS certificates.

## 16. Observability

Implement Prometheus-compatible metrics and Grafana dashboards where practical.

Track:
- events/sec
- queue depth
- processing latency
- retry rate
- DLQ count
- n8n execution success/failure
- Odoo latency/error rate
- Kyqra latency/error rate
- Telnexa latency/error rate
- Klyrow latency/error rate
- webhook delivery rate
- circuit breaker state
- CPU/RAM/disk
- database health

Add alert-ready thresholds.

## 17. Audit logging

Create immutable-style audit records for:
- admin actions
- service credential changes
- workflow deployment changes
- manual replay/retry
- tenant changes
- firewall/integration setting changes where visible to application

Include actor, timestamp, action, object, previous/new metadata where safe, and correlation ID.

Never log secrets.

## 18. Workflow safety controls

Add safeguards for actions with external impact:
- bulk SMS
- bulk email
- mass Odoo updates
- destructive contact merges

Support thresholds requiring approval or feature flags.

Use safe mode in staging/test environments.

Do not accidentally send real bulk communication during automated tests.

## 19. Rate limits and quotas

Implement per-tenant/service limits for:
- event ingestion
- API calls
- workflow starts
- crawler callbacks
- SMS requests
- email requests

Return standardized retry metadata.

Prevent one tenant from exhausting shared infrastructure.

## 20. Developer platform

Create internal/external developer documentation:
- OpenAPI specs
- webhook specs
- event schemas
- auth patterns
- idempotency behavior
- error model
- example payloads
- SDK-friendly endpoints

Generate machine-readable OpenAPI where practical.

## 21. Health and readiness

Provide:
- `/health`
- `/ready`
- dependency-specific health

Readiness should fail if critical dependencies are unavailable while liveness remains healthy where appropriate.

n8n workflow health must be measurable separately from n8n process health.

## 22. Backup and disaster recovery

Back up:
- middleware database/state
- queue/event metadata where required
- n8n database/configuration
- workflow exports
- reverse proxy config
- application config

Document and test restore procedures.

Create a clean-server recovery runbook.

## 23. CI/CD and Git workflow

Use the existing repository and production branch carefully.

Implement major work on:
- `agent/middleware-n8n-control-plane`

Add CI for:
- lint
- unit tests
- integration tests
- event schema validation
- OpenAPI validation
- Docker build/Compose validation
- n8n workflow JSON validation where possible
- secret scanning

Push changes and open a PR back to `release/production-activation`.

Do not put production secrets into GitHub Actions.

## 24. Testing

Create automated tests covering at least:

### Security
- valid/invalid service API key
- revoked key
- HMAC valid/invalid
- replay rejection
- RBAC
- tenant isolation

### Event bus
- valid event
- malformed event
- unsupported version
- duplicate event
- retry
- DLQ
- manual replay

### Odoo
- create/update through service layer
- duplicate prevention
- unavailable Odoo circuit breaker
- recovery after outage

### n8n
- valid workflow trigger
- failed workflow handling
- error workflow
- retry behavior
- workflow deployment/versioning

### Kyqra
- completed job event
- duplicate result
- failure event

### Telnexa
- inbound SMS
- delivered DLR
- failed DLR
- duplicate DLR
- opt-out event

### Klyrow
- delivered event
- hard bounce
- complaint
- unsubscribe
- duplicate event

### Infrastructure
- private endpoints not publicly exposed
- TLS renewal dry-run
- reboot/restart persistence
- backup
- restore validation

Do not use real bulk sends for testing.

## 25. Documentation

Create/update:
- `README.md`
- `ARCHITECTURE.md`
- `SECURITY.md`
- `DEPLOYMENT.md`
- `DISASTER_RECOVERY.md`
- `docs/EVENT_MODEL.md`
- `docs/API.md`
- `docs/N8N_GOVERNANCE.md`
- `docs/ODOO_INTEGRATION.md`
- `docs/KYQRA_INTEGRATION.md`
- `docs/TELNEXA_INTEGRATION.md`
- `docs/KLYROW_INTEGRATION.md`
- `docs/CONSENT_PREFERENCES.md`
- `docs/OPERATIONS.md`
- `docs/OBSERVABILITY.md`
- `DEPLOYMENT_REPORT.md`

## 26. Priority plan

### P0 — Production control-plane foundation
Complete first:
- service identities
- event envelope/contracts
- idempotency
- HMAC/replay protection
- queue/DLQ
- correlation IDs
- Odoo adapter
- n8n governance baseline
- Kyqra/Telnexa/Klyrow integrations
- consent/preference enforcement
- operations console
- observability
- backups
- tests

### P1 — Advanced operations
Then:
- circuit breakers
- workflow registry/versioning UI
- richer analytics
- manual replay tooling
- approval gates
- advanced tenant quotas

### P2 — Enterprise scale
Then:
- horizontally scaled event workers
- multi-node n8n workers if architecture supports it
- HA databases/queues
- advanced SSO/SAML/OIDC
- audit export/SIEM integration

## Working rules

Work autonomously.

Inspect existing production behavior before modifying it.

Do not replace working private ingress, Odoo integration, or n8n workflows blindly.

Back up shared configuration before changes.

Do not write directly to Odoo PostgreSQL.

Do not expose internal databases/queues publicly.

Do not commit secrets.

Do not weaken security to make tests pass.

Do not trigger real bulk SMS/email during automated testing.

Fix routine failures and continue.

Only stop for missing credentials, provider/DNS actions, or destructive changes affecting unrelated production data.

## Definition of done

The mission is complete when:
- middleware is the authoritative integration/security layer
- n8n is governed and versioned
- Odoo integration goes through a documented adapter
- Kyqra, Telnexa, and Klyrow integrations work privately
- event schemas are versioned and validated
- idempotency/replay protection works
- queue/DLQ/replay works
- tenant isolation passes
- consent/preferences are enforced
- operations console works
- correlation tracing works end-to-end
- observability and alerts are in place
- TLS auto-renew is configured for public interfaces
- backups/restore are validated
- automated tests pass
- documentation is complete
- changes are pushed on a dedicated branch and a PR is opened

Proceed continuously through implementation, deployment, testing, documentation, Git push, and PR creation.