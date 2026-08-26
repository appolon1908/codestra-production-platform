# Unified SMS + Email Middleware Control Plane — Autonomous Codex Mission

You have full autonomy to extend the existing middleware/n8n control plane in `appolon1908-hue/codestra-production-platform` so SMS through Telnexa and email through Klyrow behave as first-class channels behind one secure, auditable, tenant-aware communications layer.

## Environment

Middleware server:
- Public IP: `65.109.65.169`
- Private vSwitch IP: `10.40.0.1`
- Hosts middleware, Odoo, n8n, and existing business logic

Shared communications/application server:
- Public IP: `37.27.128.39`
- Private vSwitch IP: `10.40.0.2`
- Telnexa SMS/Jasmin runs here
- Klyrow email/Mautic/Postal runs here

Repositories:
- Middleware: `appolon1908-hue/codestra-production-platform`
- Telnexa: `appolon1908-hue/telnexa`
- Klyrow: `appolon1908-hue/klyrow.com`

Use the existing branch:
- `agent/middleware-n8n-control-plane`

Preserve existing production behavior. Do not bypass existing private ingress, mTLS, Odoo adapters, n8n governance, tenant controls, or service identities. Inspect before changing.

## Primary objective

Deliver one unified communications control plane for SMS and email.

All application/business traffic should follow this model:

```text
Odoo / n8n / internal apps
        ↓
Middleware Communications Control Plane
        ├── identity / tenant
        ├── consent / preferences
        ├── auth / RBAC
        ├── idempotency
        ├── billing / usage
        ├── routing / channel policy
        ├── audit
        ├── retries / DLQ
        └── observability
              ├── SMS → Telnexa → Jasmin → SMPP
              └── Email → Klyrow → Mautic/Postal → SMTP
```

Inbound/event flow:

```text
Telnexa/Klyrow
   ↓
Middleware event ingress
   ↓
Normalize / validate / deduplicate / audit
   ↓
Odoo + n8n workflows
```

Do not let Odoo or n8n call raw Jasmin, Postal, Mautic, Redis, RabbitMQ, or databases directly.

## 1. Unified communications API

Build or complete a versioned API under `/v1`.

Required endpoints should include equivalents of:

- `POST /v1/messages/sms`
- `POST /v1/messages/email`
- `GET /v1/messages/:id`
- `GET /v1/messages/:id/events`
- `GET /v1/messages`
- `POST /v1/messages/:id/cancel` where supported
- `POST /v1/messages/:id/retry` where safe
- `GET /v1/customers/:id/preferences`
- `PUT /v1/customers/:id/preferences`
- `POST /v1/events`
- `GET /v1/health`
- `GET /v1/ready`

Every request must support:
- tenant/customer identity
- request ID
- correlation ID
- idempotency key
- authenticated service/user identity
- server-side authorization
- structured errors
- audit trail

Do not expose raw channel-provider credentials through this API.

## 2. Unified message model and communications ledger

Create one canonical communications ledger covering both SMS and email.

Each message record must support at minimum:
- internal message ID
- channel: `sms` or `email`
- tenant ID
- customer/contact ID
- external/client reference
- correlation ID
- idempotency key
- direction: outbound/inbound
- source application
- campaign/workflow ID where applicable
- sender identity
- recipient
- normalized destination/email
- content metadata without exposing sensitive content unnecessarily
- provider/system: Telnexa or Klyrow
- downstream provider/connector where known
- status
- cost estimate
- final cost
- currency
- created/submitted/accepted/sent/delivered/failed timestamps
- provider error/status code
- retry count
- webhook/event state
- audit metadata

Status normalization should support a common lifecycle where possible, while preserving channel-specific details.

Common states:
- created
- validated
- blocked
- queued
- accepted
- sent
- delivered
- failed
- rejected
- cancelled

SMS-specific examples:
- expired
- undeliverable
- inbound_received

Email-specific examples:
- deferred
- bounced
- complained
- opened
- clicked
- unsubscribed

Preserve raw provider status separately from normalized status.

## 3. Unified contact identity

Build or formalize one customer/contact identity mapping across:
- Odoo
- Telnexa
- Klyrow
- n8n workflows

Maintain mappings for:
- Odoo partner/contact ID
- tenant ID
- customer ID
- normalized phone numbers
- normalized email addresses
- channel-specific identities

Do not create duplicate Odoo contacts because one event came from SMS and another from email.

Use middleware for entity mapping and Odoo service calls.

Do not write directly to Odoo PostgreSQL.

## 4. Consent and preference center

Create a centralized consent/preference model owned by middleware.

Support at minimum:
- SMS marketing consent
- SMS transactional permission
- email marketing consent
- email transactional permission
- global unsubscribe
- channel-specific unsubscribe
- topic/category preferences
- consent source
- consent timestamp
- consent policy/version
- proof/reference metadata where available
- revocation timestamp
- country/region metadata where useful

All outbound marketing requests must pass consent/preference checks before dispatch.

Transactional exceptions must be explicit and auditable.

Do not silently convert a marketing send into transactional traffic.

## 5. SMS-specific middleware integration

Implement Telnexa as the SMS channel adapter.

Outbound flow:

```text
Middleware
→ consent/policy check
→ tenant quota/balance check
→ Telnexa API
→ Jasmin
→ SMPP provider
```

Support:
- sender ID validation
- E.164 normalization
- Unicode/multipart metadata
- destination restrictions
- quiet-hours rules where configured
- API/SMPP customer mapping
- Telnexa billing reservation/finalization integration
- idempotent submit

Inbound/event processing must support:
- inbound SMS
- DLR delivered
- DLR failed
- expired
- undeliverable
- provider reject
- provider unavailable
- provider recovery

Normalize Telnexa events into the unified event model.

## 6. SMS opt-out handling

Implement configurable inbound keyword handling for compliant messaging workflows.

Support standard keywords where applicable, including configurable handling for examples such as:
- STOP
- START
- HELP
- UNSUBSCRIBE

Do not assume one legal rule globally; make country/provider policy configurable.

On a valid opt-out:
- update middleware preference/consent state
- publish an event
- update Odoo through approved service/API
- prevent future applicable SMS sends
- notify n8n if workflow hooks are configured
- audit the change

## 7. Email-specific middleware integration

Implement Klyrow as the email channel adapter.

Outbound flow:

```text
Middleware
→ consent/suppression check
→ tenant quota/billing check
→ Klyrow API
→ Mautic/Postal
→ SMTP
```

Support:
- transactional vs marketing classification
- sender/domain authorization
- template/campaign references
- suppression enforcement
- unsubscribe enforcement
- idempotent send
- callback metadata

Inbound/event processing must support:
- accepted
- queued
- sent
- delivered
- deferred
- bounced
- complained
- opened
- clicked
- unsubscribed
- campaign completed/failed

Normalize Klyrow events into the unified event model.

## 8. Email suppression and complaint policy

Create centralized middleware state for:
- hard bounce suppression
- repeated soft bounce thresholds
- complaint suppression
- global unsubscribe
- list/topic unsubscribe
- invalid address state

Klyrow may maintain its own suppression list, but middleware must also enforce authoritative business-level suppression rules before sending.

Synchronize suppression state where practical and avoid loops.

## 9. Unified event envelope

All channel events must use a standard versioned envelope.

Required fields:
- `event_id`
- `event_type`
- `event_version`
- `timestamp`
- `correlation_id`
- `causation_id` where available
- `tenant_id`
- `customer_id` where applicable
- `message_id`
- `channel`
- `source_service`
- `provider`
- `request_id`
- `idempotency_key`
- `payload`
- `metadata`

Examples:
- `sms.accepted`
- `sms.sent`
- `sms.delivered`
- `sms.failed`
- `sms.received`
- `sms.optout`
- `email.accepted`
- `email.delivered`
- `email.bounced`
- `email.complained`
- `email.opened`
- `email.clicked`
- `email.unsubscribed`

## 10. Correlation IDs end-to-end

Every communication must have one correlation ID from initial business request through final provider event.

Track through:
- Odoo/n8n request
- middleware API
- queue
- Telnexa/Klyrow
- provider submission
- DLR/bounce/event
- middleware event processor
- Odoo/n8n updates

Include correlation IDs in logs, database records, audit logs, retry records, and event payloads.

## 11. Idempotency and duplicate protection

Implement idempotency for all send and event-processing paths.

Duplicate API requests must not:
- send SMS twice
- send email twice
- charge twice
- create duplicate Odoo activities
- trigger duplicate business workflow effects

Duplicate DLRs/webhooks/events must not create duplicate final state transitions.

Store idempotency results with a configurable retention policy.

## 12. Durable event outbox/inbox

Implement transactional outbox/inbox patterns where practical.

For outbound channel events:
- commit business state
- persist event/outbox record
- deliver asynchronously
- mark delivered/retrying/dead-lettered

For inbound provider events:
- authenticate
- persist inbox event
- deduplicate
- process asynchronously
- record outcome

State must survive container restarts/server reboots.

## 13. Retry, DLQ, and replay

Use bounded exponential backoff.

Create separate retry/dead-letter handling for:
- Telnexa API failures
- Klyrow API failures
- Telnexa event webhook failures
- Klyrow event webhook failures
- Odoo update failures
- n8n trigger failures

Admin operators must be able to inspect and manually replay failed events.

Manual replay must require authorization and create an audit record.

Never retry forever.

## 14. Circuit breakers and dependency health

Implement circuit breakers for:
- Telnexa
- Klyrow
- Odoo
- n8n

Track states:
- closed
- open
- half-open

If a downstream service is unavailable:
- do not hammer it
- queue safe work
- expose degraded state
- automatically recover when healthy

Do not mark the entire middleware dead if one optional channel is degraded.

## 15. Channel-routing policy

Create a policy layer that can select or sequence channels based on explicit business rules.

Examples:
- preferred channel from customer profile
- send email first, SMS fallback only if configured
- SMS for urgent transactional messages
- email for long-form communication
- block marketing channel if no consent
- fallback only when policy explicitly allows it

Do not automatically convert failed email into SMS without an explicit tenant/workflow rule and applicable consent.

Expose policy decisions in audit logs.

## 16. Usage metering and billing integration

Create unified usage metering across SMS and email.

Track at minimum:
- tenant
- channel
- message count
- SMS segment count
- email recipient count
- provider/system
- estimated cost
- final cost
- customer charge
- currency
- billing period
- status

For Telnexa, integrate with its real-time wallet/rate/ledger system rather than duplicating authoritative balance calculations incorrectly.

For Klyrow, meter usage and provide billing integration points appropriate to the Klyrow SaaS model.

Middleware should provide aggregate usage and reconciliation views.

Never use floating-point arithmetic for money.

## 17. Odoo integration

Use middleware's approved Odoo API/service layer.

Support mappings for:
- contact preferences
- communication history
- inbound SMS activities
- outbound SMS status
- outbound email status
- bounce/complaint status
- unsubscribe state
- billing/usage summaries where appropriate

Do not write directly to Odoo database tables.

Make Odoo updates idempotent.

## 18. n8n integration and governance

Middleware should publish normalized business events to n8n.

Recommended events:
- `sms.received`
- `sms.delivered`
- `sms.failed`
- `sms.optout`
- `email.delivered`
- `email.bounced`
- `email.complained`
- `email.unsubscribed`
- `communication.failed`
- `communication.preference_changed`

Do not let channel services call arbitrary public n8n webhooks directly.

Use the existing n8n governance model:
- versioned workflows
- dev/staging/prod promotion
- standardized error handling
- reusable subflows
- Git-backed workflow exports where already established

## 19. Service-to-service security

Use private vSwitch communication whenever practical:
- middleware `10.40.0.1`
- Telnexa/Klyrow host `10.40.0.2`

Use existing private HTTPS/mTLS ingress if already deployed.

Use separate service identities and secrets:
- Telnexa ↔ middleware credentials
- Klyrow ↔ middleware credentials

Do not reuse credentials across channels.

For webhooks/API calls use:
- API/service identity
- HMAC-SHA256 signing where appropriate
- timestamp freshness
- replay protection
- constant-time signature comparison

Do not expose secrets in URLs or logs.

## 20. Middleware operations console

Build or extend an admin operations console with a Communications section.

Show:
- SMS health
- email health
- Telnexa connectivity
- Klyrow connectivity
- Odoo connectivity
- n8n connectivity
- message throughput by channel
- delivery/failure rates
- bounce/complaint rates
- inbound SMS volume
- opt-out counts
- consent changes
- queue depth
- retry backlog
- DLQ count
- circuit breaker state
- event latency
- billing/usage summaries
- correlation-ID search
- message timeline
- manual replay controls

All privileged actions must be audited.

## 21. Tenant and RBAC controls

Enforce tenant isolation server-side.

One tenant must not access another tenant's:
- messages
- events
- preferences
- API keys
- usage
- billing summaries
- webhooks
- logs

Use RBAC for platform admins, operations, support/read-only, billing, and tenant-scoped roles as appropriate.

## 22. Observability

Add Prometheus-compatible metrics and structured logging for:
- SMS requests
- email requests
- send success/failure
- provider latency
- DLR/bounce latency
- event-processing latency
- retries
- DLQ
- circuit breaker state
- consent blocks
- suppression blocks
- idempotency hits
- Odoo failures
- n8n failures

Logs should contain correlation/request/message IDs, but never credentials or full authorization headers.

## 23. Security and compliance safeguards

Implement:
- request validation
- rate limiting
- secure secret storage
- tenant isolation
- audit logs
- API key rotation
- webhook destination validation
- SSRF protections
- replay protection
- least-privilege networking
- dependency scanning where available
- secure cookies/headers for any UI

Do not build features intended to bypass anti-spam, carrier, provider, or legal controls.

Do not send unsolicited bulk SMS or email.

## 24. Docker and deployment

Dockerize new middleware components where practical.

Use:
- health checks
- restart policies
- persistent volumes
- isolated networks
- resource limits
- safe migrations
- backups before schema changes

Do not disturb unrelated production services.

## 25. Automated testing

Create tests covering at minimum:

### Unified API
- valid SMS request
- valid email request
- invalid auth
- tenant isolation
- idempotency
- correlation ID propagation

### SMS
- consent pass/block
- sender validation
- simulator submit success/failure
- DLR delivered/failed
- duplicate DLR
- inbound SMS
- opt-out keyword flow
- billing/idempotency interaction

### Email
- consent pass/block
- suppression block
- safe send through Klyrow test path
- delivered
- hard bounce
- complaint
- unsubscribe
- duplicate webhook

### Event system
- valid HMAC
- invalid HMAC
- expired timestamp
- replay rejection
- outbox persistence
- inbox deduplication
- retry
- DLQ
- manual replay audit

### Dependencies
- Telnexa outage
- Klyrow outage
- Odoo outage
- n8n outage
- circuit breaker open/recovery

### Security
- cross-tenant access rejected
- unauthorized admin action rejected
- private integration ports not publicly exposed
- secrets absent from Git/logs

Do not send real SMS or bulk email in automated tests.

Use Telnexa simulator and Klyrow safe/test mode until explicit production authorization exists.

## 26. Documentation

Create/update:
- `README.md`
- `DEPLOYMENT_REPORT.md`
- `docs/COMMUNICATIONS_ARCHITECTURE.md`
- `docs/UNIFIED_MESSAGE_MODEL.md`
- `docs/UNIFIED_EVENT_MODEL.md`
- `docs/CONSENT_PREFERENCES.md`
- `docs/SMS_INTEGRATION.md`
- `docs/EMAIL_INTEGRATION.md`
- `docs/ODOO_INTEGRATION.md`
- `docs/N8N_INTEGRATION.md`
- `docs/RETRY_DLQ.md`
- `docs/BILLING_METERING.md`
- `docs/SECURITY.md`
- `docs/OPERATIONS.md`

Document actual ports, service identities, event schemas, retry policies, and remaining manual actions.

## 27. Git workflow

Continue on:
- `agent/middleware-n8n-control-plane`

Commit logically grouped changes.

Push the branch.

Open or update a PR to:
- `release/production-activation`

Respect branch protection and required validation checks.

Do not force-push protected branches.

## 28. Definition of done

This mission is complete only when all locally achievable items are implemented and tested:

- unified `/v1/messages/sms` and `/v1/messages/email` APIs work
- canonical communications ledger exists
- contact identity mapping works
- centralized consent/preferences work
- SMS opt-out workflow works
- email suppression/unsubscribe workflow works
- Telnexa adapter works
- Klyrow adapter works
- unified event envelope works
- correlation IDs work end-to-end
- idempotency works
- durable outbox/inbox work
- retry/DLQ/replay work
- circuit breakers work
- channel policy layer works
- usage metering works
- Odoo updates work through middleware APIs
- n8n events work through governed workflows
- tenant isolation passes
- operations console shows both channels
- metrics/logging work
- safe restart persistence passes
- docs are complete
- branch is pushed
- PR is opened/updated

Production launch remains gated on real provider credentials, approved test destinations, DNS/PTR/TLS where applicable, and explicit authorization for external SMS/email delivery.

## Working rules

Proceed autonomously.

Inspect before modifying production behavior.

Fix routine build, migration, test, and deployment failures without stopping.

Back up configuration and databases before destructive or schema-changing work.

Do not disable security controls to make tests pass.

Do not commit secrets.

Do not invent provider credentials.

Do not send real bulk SMS or email during validation.

Only stop for:
- missing external credentials
- provider/DNS actions requiring owner/provider control
- destructive changes affecting unrelated production data
- an existing integration whose behavior cannot safely be inferred
