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
| Production platform base | `appolon1908-hue/codestra-production-platform:release/production-activation` | `7d16bcd58260f8329655b621b4f01a1e3a1e5576` | clean protected base after PR #359 merged |
| Production mission PR source | `docs/production-activation-master-mission-20260912` | `738e5ca439714c4fc380c46522c79a4c075512eb` | merged as protected-base revision above |
| Keycloak (service-auth scope only) | `appolon1908-hue/Keycloak:main` | `04845e3e47595fedde82957b97dd7c3ce0f9ae41` | remote exact head inspected |
| Caddy (private-route/TLS scope only) | `appolon1908-hue/Caddy:main` | `dc6f7e4447d76d611d9b8ce9068b34e87b90d948` | remote exact head inspected |
| n8n | `appolon1908-hue/N8N:main` | `dd100d8ebd17f7eb90871522e74863dedbccd2e9` | exact remote head plus platform workflow inventory; email workflows inactive |

The revision in this document is inventory evidence, not a release manifest.
The candidate release manifest must be regenerated after all component changes
are approved and immutable artifacts exist.

## Authority map

| Concern | Canonical authority | Classification | Finding |
| --- | --- | --- | --- |
| Business record and user-visible outcome | Odoo | PARTIAL | Durable Middleware callback records exist, but outbound transactional mail still has a direct SMTP path and read-back does not yet expose the complete lifecycle vocabulary. |
| Policy, tenant authorization, orchestration, projection, and metering control | Middleware | PARTIAL | The communications service is the canonical control-plane API and has durable commands/events, tenant checks, idempotency, and usage projection. Its runtime binding is still declared `UNVERIFIED_TEMPLATE_ONLY`, and production callback/send switches are closed. |
| Delivery authority and provider lifecycle | Klyrow | PARTIAL | The canonical Middleware adapter terminates at Klyrow `POST /v1/email/messages`; provider outbox, callbacks, suppressions, and durable events exist. Main still enforces SAFE/one-message canary. Candidate PR #126 adds strict enforcement of Middleware's command-bound post-canary authority without making Klyrow a second policy store. |
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
| PARTIAL | Main has no durable, versioned `TRANSACTIONAL_PRODUCTION` policy. Candidate Middleware PR #263 adds the authoritative policy with expiry, bounded scope, quotas, kill switches, privileged activation, append-only audit, and exact-release binding; it is not merged or deployed. | Complete protected review/CI, then certify the exact immutable candidate in staging. |
| PARTIAL | Campaign execution has separate disabled/canary/production environment switches. | Keep campaign disabled. Do not reuse or activate its broad production boolean. Require a later separate compliance policy and authorization. |
| OBSOLETE | Scattered booleans alone as proof of production authorization. | Retain them only as outer fail-closed circuit breakers; they must not substitute for the durable authorization policy. |

### Tenant, domain, sender, recipient, and message authorization

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Middleware validates tenant, sender, domain, stream, suppression, and marketing consent before command creation. | Preserve as control-plane authorization. |
| EXISTS | Klyrow verifies tenant state, domain verification, allowed sender, stream, suppression, sandbox recipients, resource suspensions, warm-up controls, and daily tenant quota. | Preserve as delivery-boundary defense in depth. |
| PARTIAL | Main has no post-canary production attestation. Middleware PR #263 creates the complete authorization record and injects a command-bound attestation after caller validation; Klyrow PR #126 validates it over the exact private service identity and again at worker time. | Merge/certify both exact heads together; never treat caller JSON or a Klyrow-local row as production authorization. |
| EXISTS | Klyrow `platform_admin` mutations require an exact owner identity, OIDC issuer/subject, verified email, fresh MFA, non-service identity, and local membership. | Preserve for Klyrow-owned delivery controls. Middleware production-policy mutations use the separate `production-operator` capability; ordinary tenant roles, workflows, and business users are denied. |

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
| PARTIAL | Middleware's body-bound HMAC callback ingress has TTL/replay protection and a durable raw inbox. PR #263 now projects the dedicated Klyrow callback into the canonical communication record by original command identity, including cross-process lookup. | Complete protected CI and staging callback/replay/out-of-order proof. |
| PARTIAL | Odoo `codestra_middleware_bridge` stores durable callback records. Candidate Odoo work adds an immutable transactional outbox/read-back projection with the full requested lifecycle vocabulary. | Complete Odoo runtime review/test and exact-candidate staging read-back. |
| PARTIAL | Main has no canonical outbound transactional-email client for Middleware. Candidate Odoo work adds only that missing opt-in bridge, defaults both control switches off, commits intent before POST, and uses GET-only reconciliation after an uncertain result. | Review/merge with the matching `odoo-email` Keycloak identity; do not activate legacy direct SMTP for this path. |

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
| PARTIAL | Klyrow has tenant daily quota, warm-up and abuse controls. Middleware PR #263 adds append-only minute/hour/day reservations and cross-process idempotency serialization. | Preserve; prove concurrent limits and tenant isolation in protected CI/staging. Do not increase defaults. |

### Metering

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | Klyrow creates a usage event in the same transaction as one logical message; Middleware maintains a usage projection. | Preserve and prove that replay does not increment and one logical canary equals one metered send. |
| PARTIAL | Exact-candidate reconciliation between Klyrow provider acceptance, usage event, Middleware projection, and Odoo state is not certified. | Add a release-evidence query/test and controlled canary evidence. |

### Audit logging

| Classification | Finding | Required action |
| --- | --- | --- |
| PARTIAL | Klyrow has general audit records. Middleware PR #263 adds hash-chained production-policy before/after audit events with actor, environment, action, change ID, correlation ID, reason, and result. | Complete protected review and retention/access certification. |

### Odoo integration

| Classification | Finding | Required action |
| --- | --- | --- |
| PARTIAL | Durable inbound delivery status exists. | Complete lifecycle vocabulary and backend-derived display. |
| DUPLICATE | Direct SMTP outbound integration coexists with the desired control-plane path. | Inventory callers, migrate transactional sends to Middleware, then deprecate without breaking existing mail infrastructure. |
| PARTIAL | Canonical transactional outbound transport is absent from main and implemented in the candidate `codestra_email_middleware` module. | Complete protected review/runtime tests; keep `CODESTRA_EMAIL_ENABLED=false` and `ALLOW_LIVE_EMAIL=false` until authorization. |

### n8n workflows

| Classification | Finding | Required action |
| --- | --- | --- |
| EXISTS | The exact N8N main catalog declares transactional send, CRM follow-up, delivery reconciliation, suppression, unsubscribe and inbound workflows as `DESIGN_ONLY`/`active:false`; `EMAIL_SEND=false`, direct Klyrow/Postal/SMTP access is prohibited, and direct email-send nodes are excluded. | Keep inactive until exact-candidate staging certification and explicit need. All writes must remain through Middleware. |
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
| PARTIAL | Historical `PRODUCTION-SOURCE-LOCK.yaml` reports `status: FAIL`, `production_certified: false`, and `deployment_authorized: false`. Mission PR #359 is merged, but component PRs and an exact immutable cross-repository candidate are not yet approved. | Obtain CODEOWNER/independent approval, merge exact component heads, then generate the candidate manifest with all SHAs, digests, config/migration versions, timestamp, and change ID. |

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

1. Keep the durable transactional-production policy, audit, quotas, and
   privileged kill switch in Middleware; Klyrow validates the command-bound
   attestation and never becomes a parallel policy authority.
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

`TRANSACTIONAL_POLICY=CANDIDATE_NOT_MERGED`

`CAMPAIGN_MODE=DISABLED`

No live activation is permitted from this inventory. Exact candidate source,
staging, DKIM rotation, fresh restore, rollback, authorization, controlled
canary, callback, metering, suppression, and observability evidence remain
mandatory gates.
