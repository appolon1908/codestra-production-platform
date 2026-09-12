# Codestra transactional email production certification status

**Evidence cutoff:** 2026-09-12

**Release/change ID:** `EMAIL-PROD-20260912-01` (candidate only; not authorized)

**Decision:** `NOT_AUTHORIZED`

**Transactional state:** `SAFE / candidate source only`

**Campaign state:** `DISABLED`

**External effects in this change:** none

This is the single index for the production-email certification package. It
does not authorize a deployment, a DNS mutation, a credential change, or a
message send. A source test is not promoted to production evidence. Values are
`PASS` only when the required exact-candidate evidence exists; otherwise they
are explicitly `FAIL` or `BLOCKED`.

## Candidate source inventory

| Component | Exact candidate revision | Review state | Artifact state |
| --- | --- | --- | --- |
| Odoo | `0c2c1328d596ab9a00914aed1a9d91506e1cc33a` | PR #131 open; exact-head checks running; required review pending | no immutable production image digest |
| Middleware | `55328e8881258dfd102c9f07d34a46b3b30cb101` | PR #263 open; exact source and merge-result checks green; required review pending | CI build passed; production digest not fixed |
| Klyrow | `269c75538ed498c9afdc6bb279c7379094daf787` | PR #126 open; frontend/test/secrets/image checks green; required review pending | production digest not fixed |
| Keycloak desired state | `2f9cafb62a639bd10c044060dc4e0e7902e4f979` | PR #115 open; protected trust update and production credentials pending | configuration only; not applied |
| n8n | `dd100d8ebd17f7eb90871522e74863dedbccd2e9` | protected main inspected; email workflows `DESIGN_ONLY`, inactive | not in the send critical path |
| Caddy | `dc6f7e4447d76d611d9b8ce9068b34e87b90d948` | protected main inspected for the existing private mTLS route | no candidate change |
| Production platform protected base | `7d16bcd58260f8329655b621b4f01a1e3a1e5576` | PR #359 merged | follow-up branch is not a release |

No production release SHA, signed cross-repository manifest, candidate image
tuple, configuration version, or rollback artifact is fixed yet. Middleware's
production-control change intentionally adds no migration: it reuses the
existing certified communications schema and `middleware_event_ledger`. The
Odoo addon version is `19.0.1.0.0`.

## Source evidence completed

- Middleware exact candidate CI is green for source/merge validation,
  PostgreSQL/Redis, NATS, Temporal, container builds/security, CodeQL,
  connector contracts, observability contracts, and synthetic no-effect E2E.
  The full local suite reported 2,816 passed, 194 skipped, plus 94 passing
  subtests.
- Klyrow exact candidate CI is green for frontend, tests, secret scanning, and
  image build. Its focused authorization/attestation suite reported 72 passed
  and one PostgreSQL-only skip.
- Odoo source tests pass. The full immutable-image Odoo 19/PostgreSQL 17.6
  runtime job installed and tested all 155 reviewed modules, passed browser and
  administrator/schema audits, and passed a disposable paired database and
  filestore restore. This is test-environment recovery evidence, not the
  required fresh production backup/restore rehearsal.
- Platform callback compatibility tests pass: 212 tests cover signed ingress,
  replay, normalized delivery/bounce/defer/complaint/unsubscribe forwarding,
  and the existing Odoo callback routing surface.
- Keycloak identity, service-access, secret-segregation, password-reset,
  workflow, and runtime-hardening checks pass until the repository's expected
  production credential certification gate. PR #115 remains red because those
  credentials are incomplete and the proposed executable-closure change has
  not received independent protected approval.

## Sanitized current-runtime observations

These observations describe the installed system, not the candidate above.

- The active Klyrow gateway reports source
  `da9d85891a4e313748e309aed86662d6c03d26bb` and digest
  `sha256:1b0caed0283f03bf3e1f05e8411ca7e28f30ab42c4b854b570471a22671a740b`.
  It is therefore not the candidate source.
- Klyrow is healthy, but the post-canary production path remains closed. The
  durable one-message allowance is already consumed.
- Sanitized counts observed during reconciliation were 27 logical messages,
  15 delivered outbox records, and provider events comprising 502 delivered,
  four bounced, one complained, and 25 held. Callback queues were empty when
  observed; that does not prove the candidate end-to-end callback path.
- Postal reports the existing 14 domains' ordinary SPF, DKIM, MX, and
  return-path checks as OK with current selector `S9A5KX`. Receiver-side
  authentication for a candidate canary and the required DKIM security
  rotation are not certified.
- A recent encrypted operational backup exists, but it is not the final
  exact-candidate recovery point and has not completed the required isolated
  production restore rehearsal.
- The checked-in production source lock says `source_lock_status: FAIL`,
  `production_certified: false`, and `deployment_authorized: false`.

## Required production gate matrix

| Gate | Status | Evidence / blocker |
| --- | --- | --- |
| `RELEASE_SOURCE_CERTIFIED` | **FAIL** | No merged immutable cross-repository release; checked-in source lock is FAIL. |
| `PROTECTED_CI` | **FAIL** | Middleware and Klyrow candidate checks are green, but Odoo/platform checks and reviews remain pending and Keycloak exact-head certification is red by design. |
| `STAGING_CERTIFIED` | **BLOCKED** | Exact candidate has not been deployed to isolated staging and the required auth/routing/restart/alert matrix has not run. |
| `DKIM_ROTATION_CERTIFIED` | **BLOCKED** | New selectors/keys have not been generated, published, signed, verified, or retired in controlled batches. See `DKIM_CERTIFICATION.csv`. |
| `BACKUP_VERIFIED` | **BLOCKED** | No fresh encrypted backup bound to the final release tuple and change ID. |
| `RESTORE_REHEARSAL` | **BLOCKED** | No isolated restore of the final production recovery point with timing and critical email/audit-state read-back. |
| `ROLLBACK_REHEARSAL` | **BLOCKED** | Stop-new-sends plus callback-preserving application/config/database rollback has not been rehearsed for the final tuple. |
| `PRODUCTION_AUTHORIZATION` | **BLOCKED** | No owner-approved immutable policy record exists; required owners, launch window, bounded scope, quotas, release SHA, timestamps, and review/expiry are unset. |
| `TRANSACTIONAL_POLICY` | **BLOCKED** | Source implementation exists in Middleware PR #263 but is not merged, deployed, authorized, or activated. |
| `E2E_CANARY` | **BLOCKED** | No owner-approved candidate live message was sent. The earlier one-message allowance is consumed and cannot authorize another send. |
| `SPF` | **BLOCKED** | Existing DNS check is OK; candidate receiver-side canary header evidence is absent. |
| `DKIM` | **BLOCKED** | Existing selector check is OK; rotation and candidate receiver-side header evidence are absent. |
| `DMARC` | **BLOCKED** | Candidate receiver-side canary header evidence is absent. |
| `CALLBACKS` | **BLOCKED** | Source replay/projection tests pass; no exact-candidate provider-to-Klyrow-to-Middleware-to-Odoo live proof exists. |
| `IDEMPOTENCY` | **BLOCKED** | Source tests cover duplicate/conflict/timeout/replay/restart cases; exact-candidate staging plus one-live-message metering proof is absent. |
| `METERING` | **BLOCKED** | Source reservation/projection exists; no exact-candidate evidence proves one logical email equals one metered send. |
| `BOUNCE_HANDLING` | **BLOCKED** | Existing source behavior and sanitized historical events exist; controlled exact-candidate hard/soft-bounce certification is absent. |
| `COMPLAINT_HANDLING` | **BLOCKED** | Existing source behavior and sanitized historical event exist; controlled exact-candidate certification is absent. |
| `SUPPRESSION` | **BLOCKED** | Source enforcement exists; no exact-candidate proof shows a post-bounce/complaint resend is stopped before the provider. |
| `OBSERVABILITY` | **BLOCKED** | Metrics/alerts are partial; exact-candidate dashboards and alert tests for the required email dimensions are incomplete. |
| `KILL_SWITCH` | **BLOCKED** | Layered switches and the audited policy control exist in source; callback-preserving emergency shutdown is not rehearsed. |
| `CONTROLLED_ROLLOUT` | **BLOCKED** | P0 certification is incomplete; P1 through P4 have not started. |
| `CAMPAIGN_MODE` | **PASS** | Campaign remains disabled and has no inferred transactional authorization. |

## Production authorization record

`NOT_PRESENT`. The Middleware candidate enforces the complete record server-side
and denies activation without it. An authorized production owner must supply
the actual change ID, tenant, domains, senders, transactional categories,
recipient scope, minute/hour/day limits, launch window, monitoring/escalation/
rollback owners, kill-switch procedure, approved final release SHA, approval
timestamp, and expiry/review date. This package does not fabricate those
values.

## Canary evidence

`NOT_RUN`. No recipient was selected, no provider action was requested, and no
receipt or authentication headers were captured. Historical provider counts
and the consumed earlier allowance are inventory only. They are not evidence
for the required candidate canary.

## Rollback position

The required emergency principle is documented as **stop new sends while
keeping callback ingestion, read-back, metrics, and audit available**. The
source controls are Middleware revoke/kill-switch plus Odoo
`ALLOW_LIVE_EMAIL=false`; provider sender/domain suspension remains defense in
depth. This is a documented procedure only until exercised against the final
staging and production tuples.

## Evidence package index

- `REPOSITORY_RECONCILIATION.md` — exact-head API/authority inventory and
  `EXISTS`/`PARTIAL`/`MISSING`/`DUPLICATE`/`OBSOLETE` decisions.
- `DKIM_CERTIFICATION.csv` — all 14 current sending domains, explicitly
  uncertified for rotation.
- `../../PRODUCTION_EMAIL_RUNBOOK.md` — activation, shutdown, provider,
  callback, reputation, DKIM, revocation, quota, credential, rollback, restore,
  and incident re-enable procedures.
- GitHub PR #359 — merged mission/base reconciliation.
- Middleware PR #263 and protected-trust maintenance PR #261.
- Klyrow PR #126, Odoo PR #131, and Keycloak PR #115.

## Remaining blockers

1. Independent/CODEOWNER approval and protected merge for every candidate,
   including the Middleware trust transition and Keycloak executable-closure
   proposal; provision the two new Keycloak secrets through protected channels
   and wire them into protected deployment without weakening workflow policy.
2. Build, sign, scan, and record immutable candidate images; generate the final
   release manifest and make the exact production source lock green.
3. Deploy those exact digests to staging and pass the complete authentication,
   policy, quota, idempotency, suppression, provider, callback, Odoo read-back,
   restart, observability, and alert matrix.
4. Rotate DKIM for all affected domains in controlled batches and record DNS,
   signing, receiver verification, and old-key revocation without exposing
   private material.
5. Create and restore a fresh encrypted release-bound backup, then rehearse
   callback-preserving rollback and record recovery time.
6. Obtain the explicit bounded production authorization record. Only then run
   P1 with one approved tenant/domain/sender and an approved recipient, capture
   SPF/DKIM/DMARC, callback, Odoo, idempotency, metering and suppression
   evidence, observe it, and expand only if the stop thresholds remain clear.
