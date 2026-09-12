# Production email repository reconciliation

**Inventory time:** 2026-09-12  
**Change scope:** Odoo -> Middleware -> optional n8n orchestration -> Klyrow -> Postal/provider -> callback -> Middleware -> Odoo  
**External effects:** none; no production flag, credential, DNS record, workflow, or recipient was changed

This is the mandatory pre-implementation inventory for
`docs/PRODUCTION_ACTIVATION_MISSION.md`. `EXISTS` means that the capability is
present in the inspected source. It does not mean that it is deployed or
production-certified. A production claim requires exact-release runtime
evidence in addition to this source inventory.

## Exact heads inspected

| Component | Repository/ref | Exact revision | Worktree state |
| --- | --- | --- | --- |
| Klyrow | `appolon1908-hue/klyrow.com:main` | `229a3d88ad159eed8fa55cb4f6312388273f554f` | clean detached checkout |
| Middleware | `appolon1908-hue/Middleware-:main` | `05c78f2ea9b56643cbbec42d8f3c0f3a763f6cf1` | clean detached checkout |
| Odoo | `appolon1908-hue/Odoo:main` | `58fbca6ecd0fa29380989642e778ba7d928a8941` | clean detached checkout |
| Production platform base | `appolon1908-hue/codestra-production-platform:release/production-activation` | `8503530cc46485fbfb322864ab199166cb922776` | PR branch rebased onto this revision |
| Production mission PR source before rebase | `docs/production-activation-master-mission-20260912` | `2e307b44fd24846d23439ac592a6f13041fea289` | remote source recorded before reconciliation |
| Keycloak (service-auth scope only) | `appolon1908-hue/Keycloak:main` | `04845e3e47595fedde82957b97dd7c3ce0f9ae41` | remote exact head inspected |
| Caddy (private-route/TLS scope only) | `appolon1908-hue/Caddy:main` | `dc6f7e4447d76d611d9b8ce9068b34e87b90d948` | remote exact head inspected |
| n8n configuration | production-platform control-plane manifests at the base revision above | `8503530cc46485fbfb322864ab199166cb922776` | source inventory only; email workflows inactive |

The revision in this document is inventory evidence, not a release manifest.
The candidate release manifest must be regenerated after all component changes
are approved and immutable artifacts exist.

## Authority map

| Concern | Canonical authority | Classification | Finding |
| --- | --- | --- | --- |
| Business record and user-visible outcome | Odoo | PARTIAL | Durable Middleware callback records exist, but outbound transactional mail still has a direct SMTP path and read-back does not yet expose the complete lifecycle vocabulary. |
| Policy, tenant authorization, orchestration, projection, and metering control | Middleware | PARTIAL | The communications service is the canonical control-plane API and has durable commands/events, tenant checks, idempotency, and usage projection. Its runtime binding is still declared `UNVERIFIED_TEMPLATE_ONLY`, and production callback/send switches are closed. |
| Delivery authority and provider lifecycle | Klyrow | PARTIAL | The canonical Middleware adapter terminates at Klyrow `POST /v1/email/messages`; provider outbox, callbacks, suppressions, and durable events exist. Only SAFE and a one-message transactional canary are enforceable; an authoritative post-canary transactional-production policy is missing. |
| Optional sequencing | n8n | EXISTS | Email lifecycle workflows are inactive and call the control plane. n8n is not the source of policy, quota, suppression, provider lifecycle, or billing truth. It is not required in the current canonical send critical path. |
| SMTP delivery | Postal/provider behind Klyrow | EXISTS | Existing provider infrastructure is preserved. This mission does not rebuild it. Production certification still needs exact-candidate health and live evidence. |
| Service identity | Keycloak plus private gateway TLS | PARTIAL | Klyrow's Middleware route requires service identity, issuer/audience/scope and tenant binding; exact-candidate staging and production authentication evidence is not yet present. |

## Requested capability inventory

### Existing email APIs

| Classification | API/capability | Decision |
| --- | --- | --- |
| EXISTS | Middleware `POST /v1/communications/messages` plus query, event, cancellation, provider-health, reputation, and usage routes | Reuse as the Odoo/business-facing API. The singular `/v1/communication/messages` is a compatibility alias, not a new authority. |
| EXISTS | Klyrow `POST /v1/email/messages` and `GET /v1/email/messages/{command_id}` | Reuse as the only canonical Middleware-to-Klyrow transport. |
| DUPLICATE | Klyrow core `/v1/messages`, hidden `/v1/email/send`, `/v1/commands`, provider-internal `/v1/internal/email/send`, and `/communications/messages` | Do not extend these for the production-policy integration. Complete a caller audit before deprecation or removal. |
| DUPLICATE | Middleware legacy `app/email` delivery runtime | Do not make it a second delivery authority. Complete a caller/data-migration audit before retirement. |

### Delivery mode and safe/canary enforcement

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Klyrow reconciles safe-mode controls and fails closed when delivery configuration is incoherent. | Preserve. |
| EXISTS | `ProductionCanaryGate` durably reserves and claims exactly one allowed transactional canary. | Preserve for `TRANSACTIONAL_CANARY`. |
| MISSING | There is no durable, versioned `TRANSACTIONAL_PRODUCTION` policy. With safe mode off, every transactional message still enters the consumed one-shot gate. | Implement one authoritative policy with expiry, scope, quotas, kill switches, privileged activation, immutable audit, and request plus worker-time enforcement. |
| PARTIAL | Campaign execution has separate disabled/canary/production environment switches. | Keep campaign disabled. Do not reuse or activate its broad production boolean. Require a later separate compliance policy and authorization. |
| OBSOLETE | Scattered booleans alone as proof of production authorization. | Retain them only as outer fail-closed circuit breakers; they must not substitute for the durable authorization policy. |

### Tenant, domain, sender, recipient, and message authorization

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Middleware validates tenant, sender, domain, stream, suppression, and marketing consent before command creation. | Preserve as control-plane authorization. |
| EXISTS | Klyrow verifies tenant state, domain verification, allowed sender, stream, suppression, sandbox recipients, resource suspensions, warm-up controls, and daily tenant quota. | Preserve as delivery-boundary defense in depth. |
| MISSING | Klyrow has no production authorization binding an approved tenant, domains, senders, recipient scope, message categories, quotas, change ID, launch window, actors, environment, and exact release. | Add to the single production-delivery policy; never trust request JSON as authorization. |
| EXISTS | Klyrow `platform_admin` mutations require an exact owner identity, OIDC issuer/subject, verified email, fresh MFA, non-service identity, and local membership. | Reuse for production-policy mutations; ordinary tenant roles and service accounts must be denied. |

### Sender identity and provider adapters

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Klyrow domain and allowed-sender models/APIs and provider delivery adapter. | Reuse. Approval in those tables is necessary but not sufficient for production authorization. |
| EXISTS | Middleware `KlyrowEmailAdapter` uses private mTLS plus OAuth2 and the canonical Klyrow API, and reads back after an ambiguous timeout rather than blindly resending. | Reuse; certify exact runtime credentials and routing in staging. |
| DUPLICATE | Odoo `codestra_klyrow_smtp` can submit directly to Klyrow/Postal SMTP. | Treat as a legacy path. Do not activate it for canonical transactional production; first replace live callers with the Middleware communications API. |

### Callbacks, message identity, and Odoo read-back

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Klyrow provider callbacks validate HMAC or Postal signatures, use replay records, attach provider IDs to platform messages, persist lifecycle events, and enqueue durable Middleware events. | Preserve; prove signature rejection, replay safety, and out-of-order behavior against the exact candidate. |
| EXISTS | `message_id`, Middleware command ID, `correlation_id`, `idempotency_key`, tenant, sender, recipient, and provider identifiers are carried or durably bound through the canonical Klyrow path. | Preserve one durable logical identity and test it end to end. |
| EXISTS | Middleware has a body-bound HMAC callback ingress with TTL/replay protection, durable inbox/projection, and Odoo delivery worker. | Preserve; the deployed ingress and Odoo delivery switches are currently closed. |
| PARTIAL | Odoo `codestra_middleware_bridge` stores durable, immutable callback records. | Extend the read-back mapping from delivered/bounced/deferred to requested, accepted, queued, provider_accepted, delivered, deferred, bounced, complained, suppressed, rejected, and failed. |
| MISSING | Odoo has no canonical outbound transactional-email client for Middleware. | Implement by adapting the existing Middleware transport pattern; do not build delivery logic inside Odoo. |

### Idempotency

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Middleware and Klyrow both persist scoped request keys and payload digests; same-content replay returns the logical result and conflicting replay fails. Callback replay records also exist. | Preserve. |
| PARTIAL | Klyrow provider-timeout and callback replay handling exist, but the complete simultaneous duplicate, restart, delayed/out-of-order callback, and queue-retry production matrix is not certified against one exact release. | Add/retain automated tests, then run staging and controlled live evidence. |

### Suppression, bounce, and complaint handling

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Klyrow creates suppression state from hard bounce and complaint events and checks suppression before provider enqueue. Middleware also checks its suppression/consent projection. | Preserve dual fail-closed enforcement. |
| PARTIAL | Source behavior exists, but no exact-candidate evidence proves that all required hard bounce, soft bounce, complaint, unsubscribe, invalid sender/domain, and quota cases stop at the correct boundary. | Certify in staging and approved provider test mechanisms; never test on unsolicited recipients. |

### Rate limits and quotas

| Classification | Finding | Required action |
| --- | --- | --- |
| PARTIAL | Klyrow has tenant daily quota, warm-up and abuse controls; Middleware has tenant controls. | Preserve, but add production-policy per-minute, per-hour, and per-day limits with tenant isolation and atomic/concurrency-safe enforcement. Do not increase defaults. |

### Metering

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Klyrow creates a usage event in the same transaction as one logical message; Middleware maintains a usage projection. | Preserve and prove that replay does not increment and one logical canary equals one metered send. |
| PARTIAL | Exact-candidate reconciliation between Klyrow provider acceptance, usage event, Middleware projection, and Odoo state is not certified. | Add a release-evidence query/test and controlled canary evidence. |

### Audit logging

| Classification | Finding | Required action |
| --- | --- | --- |
| PARTIAL | Klyrow has general audit records and Middleware has durable command/event auditability. | Add append-only production-policy audit records with actor, timestamp, environment, action, resource, before/after, change ID, correlation ID, reason, and result. |

### Odoo integration

| Classification | Finding | Required action |
| --- | --- | --- |
| PARTIAL | Durable inbound delivery status exists. | Complete lifecycle vocabulary and backend-derived display. |
| DUPLICATE | Direct SMTP outbound integration coexists with the desired control-plane path. | Inventory callers, migrate transactional sends to Middleware, then deprecate without breaking existing mail infrastructure. |
| MISSING | Canonical transactional outbound transport to Middleware. | Add only this missing integration. |

### n8n workflows

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | CP24/25/26/27/33 lifecycle workflows and communications workflow definitions exist with `active:false`. | Keep inactive until exact-candidate staging certification and explicit need. All writes must remain through Middleware. |
| OBSOLETE | Treating n8n state as production authorization, quota, suppression, metering, or provider truth. | Prohibited; no implementation found or planned. |

### Observability and alerts

| Classification | Finding | Required action |
| --- | --- | --- |
| PARTIAL | Klyrow and Middleware expose request/lifecycle/provider/queue/error metrics and the platform has dashboards/alerts. | Add missing authorization-denial, quota/rate, idempotency replay, callback latency/failure, synchronization and policy-state coverage with bounded environment/tenant/domain/sender/provider/category labels. Never label with recipients, bodies, or secrets. |
| PARTIAL | Alert definitions exist for provider and queue failures. | Test exact candidate alerts for missing callbacks, authorization bypass/denial anomaly, suppression failure, delivery latency, bounce/complaint spikes, and monitoring loss. |

### Release manifests and source locks

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | The platform provides release-manifest schemas, protected validation workflows, signed-artifact controls, rollback manifests, and source-lock tooling. | Reuse; never weaken validators. |
| PARTIAL | `PRODUCTION-SOURCE-LOCK.yaml` explicitly reports `status: FAIL`, `production_certified: false`, and `deployment_authorized: false`. PR #359 initially lacked current-base evidence and independent approval. | Rebase, run exact-head checks, obtain CODEOWNER/independent approval, then generate the candidate manifest with all component SHAs, digests, config/migration versions, timestamp, and change ID. |

### Kill switches

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Global safe/live-delivery gates, platform emergency stop, tenant and delivery-resource suspensions, and operator enable/disable scripts exist. | Preserve as layered controls. |
| PARTIAL | There is no single audited production-policy control supporting system, tenant, and sender/domain stop while leaving callback ingestion and observability available. | Add audited policy kill switches and rehearse `STOP NEW SENDS` without disabling callbacks. |

### Backup, restore, rollback, and DKIM

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Encrypted backup automation and rollback/runbook foundations exist. | Preserve. |
| PARTIAL | A current encrypted backup exists operationally, but it has not been restored as the final exact candidate into an isolated rehearsal with recovery time and critical-record validation. | Create fresh backup only during authorized cutover preparation, record SHA-256, verify encryption/integrity, and perform isolated restore. |
| PARTIAL | Rollback artifacts and stop controls exist. | Rehearse exact-candidate application/config/database rollback and prove no duplicate replay while callbacks remain live. |
| PARTIAL | All 14 domains presently pass ordinary DNS/provider checks with the current selector. | Do not redo basic DNS. Complete controlled DKIM key/selector rotation and receiver-side signing proof for each affected domain; never place private material in source/evidence. |

## Implementation boundary decided by this inventory

1. Extend Klyrow's canonical Middleware route with the missing durable
   transactional-production policy and audit/quotas/kill switches.
2. Keep the existing one-message gate as `TRANSACTIONAL_CANARY` and leave
   campaign execution closed.
3. Extend the existing Middleware projection/adapter only where required; do
   not add a second Middleware mail service.
4. Add the missing Odoo-to-Middleware transactional transport and expand the
   existing durable Odoo read-back mapping. Do not enable the legacy direct
   SMTP path for this launch.
5. Keep n8n optional and inactive until its workflows have staging evidence.
6. Use existing provider, callback, backup, source-lock, release, dashboard,
   and operator controls; add only the missing fields, checks, tests, and
   evidence.

## Current decision

`PRODUCTION_AUTHORIZATION=NOT_ACTIVE`

`TRANSACTIONAL_POLICY=MISSING`

`CAMPAIGN_MODE=DISABLED`

No live activation is permitted from this inventory. Exact candidate source,
staging, DKIM rotation, fresh restore, rollback, authorization, controlled
canary, callback, metering, suppression, and observability evidence remain
mandatory gates.
