# Telnexa SMS production repository reconciliation

Date: 2026-09-12

Scope: Odoo -> Middleware -> n8n (optional orchestration only) -> Telnexa -> Jasmin -> carrier -> DLR/MO -> Telnexa -> Middleware -> Odoo

Decision at inventory time: `NO_GO`

This is the mandatory pre-implementation inventory for the Telnexa SMS
production activation mission. It is deliberately fail-closed. Source evidence
does not prove a carrier action, production deployment, recipient delivery, or
callback.

## Reconciled source heads

| Component | Repository / branch | inspected SHA | role |
| --- | --- | --- | --- |
| Telnexa | `appolon1908-hue/telnexa` / `main` | `73abfcbfc4904859d58221cdb1dfb1ad93bf5a33` | SMS delivery and provider lifecycle authority |
| Middleware | `appolon1908-hue/Middleware-` / `main` | `05c78f2ea9b56643cbbec42d8f3c0f3a763f6cf1` | orchestration and cross-system control plane |
| Odoo | `appolon1908-hue/Odoo` / `main` | `58fbca6ecd0fa29380989642e778ba7d928a8941` | business system of record |
| production platform | `appolon1908-hue/codestra-production-platform` / `release/production-activation` | `7d16bcd58260f8329655b621b4f01a1e3a1e5576` | release and deployment authority |
| n8n | `appolon1908-hue/N8N` / `main` | `dd100d8ebd17f7eb90871522e74863dedbccd2e9` | optional workflow orchestration only |
| Keycloak | `appolon1908-hue/Keycloak` / `main` | `04845e3e47595fedde82957b97dd7c3ce0f9ae41` | workload identity authority |
| Caddy | `appolon1908-hue/Caddy` / `main` | `dc6f7e4447d76d611d9b8ce9068b34e87b90d948` | ingress/TLS evidence only |
| OpenBao | `appolon1908-hue/Codestra-OpenBao` / `main` | `5f5e3583585081e450f945440a1fab503bfa8399` | runtime secret authority |

All listed clones were clean when inspected. The release tuple must be refreshed
again immediately before certification; these SHAs are inventory inputs, not an
approved production manifest.

## Runtime facts observed

- `https://api.telnexa.co/health` returned `status=ok` and `simulator=true`.
- the Telnexa host reported healthy containers, while `LIVE_SMS_DELIVERY=false`;
- `/opt/telnexa/placeholders/smpp-provider.env` was absent;
- no real carrier submission, DLR, MO, receiver receipt, or billing debit was
  attempted during reconciliation;
- the exact-head Telnexa CI run was green, but the immutable release run was red
  because its Keycloak image scan detected a critical Netty vulnerability;
- the live billing revision was older than the inspected Telnexa `main` head;
- daily encrypted local backup execution was observed; the latest recorded
  isolated restore PASS was from 2026-09-02, not a fresh rehearsal of the
  current candidate; and
- current source documentation explicitly records real carrier credentials,
  production deployment, callback dispatch, and SMS delivery as disabled or
  absent.

## Authority and duplicate-path decision

The deployed and Middleware-consumed Telnexa authority is the commercial
`billing.app` API (`POST /api/v1/messages` plus idempotency read-back). It owns
sender admission, suppression/consent, rating, billing reservation, route
selection, dispatch, provider events, reconciliation and metering.

The additive `billing.sms_provider_service` uses separate tables, routes,
transport, callback outbox and billing reservations and is not wired into the
production compose runtime. It is classified `DUPLICATE` for this activation
path and must not be activated as a second SMS authority. Its useful contract
tests may inform the canonical implementation, but new production work belongs
in `billing.app` and its existing durable models.

The production platform's legacy private gateway/Jasmin path is also
`DUPLICATE` for outbound delivery. Middleware must call Telnexa; it must never
call Jasmin or a carrier directly. n8n stays out of provider delivery and all
authoritative policy, billing, suppression and lifecycle state.

## Feature inventory

| Capability | Classification | Evidence / required disposition |
| --- | --- | --- |
| canonical SMS submit API | `EXISTS` | Middleware adapter uses Telnexa `POST /api/v1/messages`. Preserve it. |
| read-only idempotency reconciliation | `EXISTS` | Middleware performs GET-only read-back after indeterminate outcomes. |
| durable message identity and correlation | `PARTIAL` | Odoo/Middleware/Telnexa persist identities, but Telnexa's current outbound event envelope is incompatible with Middleware's canonical envelope. |
| durable request idempotency | `EXISTS` | Telnexa rejects conflicting replay and Middleware/Odoo avoid a second POST after indeterminate submission. |
| simultaneous duplicate protection | `EXISTS` | Telnexa uses database locking/uniqueness around message idempotency. |
| delivery mode and one-message canary | `PARTIAL` | Global fail-closed flags and a durable bounded canary exist. No authorized post-canary transactional policy exists. |
| tenant authorization | `PARTIAL` | Request-side tenant and API-key binding exist. The Telnexa Keycloak client lacks the non-wildcard service-account tenant claim required by Middleware callback authorization. |
| sender identity approval | `EXISTS` | Durable sender state is enforced before dispatch. Actual carrier-approved values are absent. |
| destination authorization | `PARTIAL` | Canary allowlist and country policy exist. The owner-approved production destination/country scope is absent; USA must remain denied. |
| provider/carrier adapter | `PARTIAL` | Carrier-neutral dispatch into Jasmin exists. DIDWW capability metadata and governed runtime credential loading are missing. |
| provider credential authority | `MISSING` | OpenBao PR design exists, but reviewed policies, workload auth and runtime values are not merged or installed. |
| exact carrier throughput | `MISSING` | Provider TPS fields exist; approved DIDWW MPS/TPS is unknown and therefore must remain closed. |
| per-minute/hour/day policy quotas | `PARTIAL` | Existing rate/monthly/billing limits are substantial; one authoritative production policy with the requested windows and approval metadata is missing. |
| segment and spend ceiling | `PARTIAL` | Segment rating/metering exists. The USD 2 initial ceiling's authoritative account grain is unresolved and must not be guessed. |
| suppression/STOP handling | `EXISTS` | Telnexa durably applies STOP and blocks governed sends. Odoo performs its own preflight, but Telnexa remains final SMS authority. |
| DLR/MO ingestion | `EXISTS` | Signed, replay-safe provider inbox with normalization, monotonic transition and quarantine exists. |
| Telnexa -> Middleware callback | `PARTIAL` | Durable outbox and mTLS requirement exist, but URL, headers, signature, event names, envelope, and short-lived bearer token do not match Middleware. |
| Middleware callback inbox | `EXISTS` | OIDC, HMAC, freshness, replay guard, durable inbox, semantic-conflict rejection and immutable ledger exist. Reuse it. |
| Middleware callback route | `PARTIAL` | Protected contract is `/api/v1/telnexa/events`; approved issue contract is `/api/v1/events/telnexa`. Do not expose both as live authorities. |
| Odoo outbound integration | `EXISTS` | `codestra_sms_middleware` creates an immutable outbox and posts only after local commit. |
| Odoo delivery read-back | `PARTIAL` | Durable polling and native state projection exist. Full production callback/read-back has not been observed end to end. |
| n8n SMS workflow | `PARTIAL` | Source-only inactive workflow pack exists; it has no direct Jasmin access and is not production-authoritative. No active workflow is required for the core delivery path. |
| metering and reconciliation | `EXISTS` | Telnexa has usage, wallet/reservation/finalization and provider reconciliation records. Carrier statement reconciliation remains unproved. |
| audit history | `EXISTS` | Telnexa stores audited commercial mutations. New production-policy mutations require the same append-only evidence. |
| observability | `PARTIAL` | SMS/provider metrics exist, but carrier capability, callback backlog/missing-callback and production-policy alerts are not fully certified. |
| kill switches | `PARTIAL` | Layered flags, disabled routes/providers and canary closure exist. A single reviewed policy/read-back and rehearsed stop-new-sends action are missing. |
| signed digest-pinned images | `PARTIAL` | Billing/Jasmin/nginx/relay release jobs passed in the inspected release run; the aggregate release is red on Keycloak and current production digests are not certified. |
| backup and restore | `PARTIAL` | Encrypted local backup exists and an older restore PASS is recorded. A fresh candidate-specific restore plus off-host evidence is missing. |
| rollback | `PARTIAL` | Rollback scripts/runbooks exist. The exact candidate rollback has not been rehearsed. |
| protected source/release lock | `PARTIAL` | Main heads and checks exist. Cross-repo locks point to older Telnexa/Middleware SHAs and no approved exact candidate tuple exists. |
| campaign/bulk SMS | `PARTIAL` | Campaign models exist but production marketing authorization/compliance certification does not. Keep disabled. |

## Canonical contract to repair

One route must remain authoritative:

```text
POST https://middleware.internal.codestra.agency/api/v1/events/telnexa
```

The producer must use:

- Keycloak client credentials for `telnexa-gateway`, audience
  `middleware-api`, scope `sms.events.publish`, access-token lifetime at most
  300 seconds, and an explicit non-wildcard service-account `tenant_id` claim;
- mTLS with DNS name validation at the canonical private endpoint;
- the existing Middleware v1 raw-body HMAC contract and `X-Codestra-*`
  headers;
- a canonical `EventEnvelope`, including `received_at`, `causation_id`, and
  `source=telnexa-gateway`; and
- canonical lifecycle event types. Provider-local values remain payload fields,
  never route or tenant authorities.

For the initial rollout, one Keycloak service-account tenant assignment is
sufficient. Adding tenants requires an explicit reviewed identity update; a
wildcard remains forbidden.

## Mandatory blockers before any carrier effect

1. Select and approve the DIDWW production connection and install the actual
   credentials through reviewed OpenBao policy; never Git or ordinary env files.
2. Record the approved tenant/account, senders, non-USA destination scope,
   exact MPS/TPS, segment limits, USD 2 ceiling grain, spending owner and test
   window.
3. Merge and deploy the canonical Telnexa-to-Middleware callback contract and
   prove positive and negative mTLS/OIDC/HMAC/replay/tenant tests.
4. Remediate the critical Keycloak/Netty vulnerability without weakening the
   scanner, then make the exact-head immutable release workflow green.
5. Build, sign, verify and deploy one digest-pinned API/Jasmin/relay/Keycloak
   candidate to staging and then production; record source/config/schema tuple.
6. Run a bounded carrier sandbox certification for MT, DLR, MO, GSM-7, UCS-2,
   multipart, throttling, ambiguous outcome/read-back and billing
   reconciliation.
7. Complete fresh encrypted backup/restore and exact-candidate rollback
   rehearsals while callback ingestion and observability remain available.
8. Obtain explicit production owner, security, compliance, billing, monitoring
   and rollback approvals. Only then create and activate a limited production
   policy.

Until all blockers close:

```text
PRODUCTION_AUTHORIZATION=NOT_AUTHORIZED
TRANSACTIONAL_SMS=INACTIVE
CAMPAIGN_SMS=DISABLED
LIVE_SMS_DELIVERY=false
```

## Post-inventory source candidate

After this inventory established the missing capabilities, bounded candidates
were prepared without live effects:

- Telnexa `556277062d2a908baf1607204a0bddc2e0660b1c` adds the immutable
  authorization/current-policy control, layered kill switches, DIDWW/source
  SHA/sender/destination/category/quota/spend enforcement, acceptance and
  pre-dispatch revalidation, mounted callback identities, and the canonical
  Middleware event contract.
- Middleware `f9bc648b49a2e69aae1d7a272cb392e65888b3a4` changes the existing
  Telnexa ingress contract to the approved canonical path; it does not add a
  parallel endpoint.
- Keycloak `f3c0c1116890a0c9097473545fed045fc2010276` binds the Telnexa
  service identity to explicit multivalued `tenant_ids` service-account
  attributes and rejects hardcoded or missing tenant mapping.

These commits change the inventory classifications for source implementation,
not for certification. They are unmerged, undeployed and unapproved, and all
external blockers above remain in force.
