# Telnexa SMS production certification status

Certification timestamp: 2026-09-12T13:36:31+02:00

Current decision: `NO_GO`

Transactional status: `NOT_AUTHORIZED`

Campaign status: `DISABLED`

This package adapts the production mission to the requested Telnexa SMS path:

`Odoo -> Middleware -> n8n (optional) -> Telnexa -> Jasmin -> DIDWW -> DLR/MO -> Telnexa -> Middleware -> Odoo`

It does not certify the separate Klyrow/Postal email path. SPF, DKIM, DMARC,
bounce and email-complaint gates are not applicable to this SMS candidate.
SMS equivalents are carrier credentials, sender/destination approval, DLR,
MO, STOP/suppression, segment metering, spend controls and reconciliation.

## Candidate changes

| Repository | Candidate | PR | Result |
| --- | --- | --- | --- |
| Telnexa | `556277062d2a908baf1607204a0bddc2e0660b1c` | [telnexa#36](https://github.com/appolon1908-hue/telnexa/pull/36) | source candidate; not deployed |
| Middleware | `f9bc648b49a2e69aae1d7a272cb392e65888b3a4` | [Middleware-#267](https://github.com/appolon1908-hue/Middleware-/pull/267) | source candidate; protected trust blocked |
| Keycloak | `f3c0c1116890a0c9097473545fed045fc2010276` | [Keycloak#116](https://github.com/appolon1908-hue/Keycloak/pull/116) | source candidate; independent approval required |
| Odoo | `58fbca6ecd0fa29380989642e778ba7d928a8941` | none | inspected; unchanged |
| n8n | `dd100d8ebd17f7eb90871522e74863dedbccd2e9` | none | inspected; unchanged and non-authoritative |
| production platform | base `7d16bcd58260f8329655b621b4f01a1e3a1e5576` | this evidence branch | evidence only; not a release lock |

## Source implementation evidence

- Telnexa exact final tree: 171 tests passed; Ruff lint and formatting passed.
- Telnexa migration 010 was created, reapplied, and checked in disposable
  PostgreSQL 17; no production database was touched.
- Middleware complete local suite: 2,808 passed, 193 skipped and 94 subtests;
  a subsequent exact-SHA type-check failure was repaired and its two changed
  modules pass Ruff and mypy. PostgreSQL-only pagination tests remain for
  protected CI.
- Keycloak `bash scripts/validate.sh`: PASS, including generated configuration,
  identity contracts, workflow validation and negative tenant-mapper tests.
- Telnexa callbacks now use the single canonical Middleware route, mTLS,
  short-lived Keycloak client credentials, raw-body HMAC, durable event IDs,
  bounded retries and redacted errors.
- Telnexa production admission and pre-dispatch both validate an immutable
  authorization and the same versioned policy identity. Campaign mode and USA
  destinations are denied. The deployment interlock remains closed.
- Operator mutations are authenticated from a mounted secret file, audited,
  idempotent and optimistic-versioned. Global, tenant and sender kill switches
  stop new outbound work without disabling DLR/MO or evidence ingestion.
- The initial carrier spend ceiling is bound to the tenant's unique billing
  account, in USD, and cannot exceed USD 2.00. Quotas count segments, not API
  calls.

These results are source evidence only. They do not prove live carrier behavior,
production deployment, receiver receipt, callbacks, billing debit, alert delivery,
restore or rollback.

## Remote protected-chain evidence

| Check | Result | Evidence / disposition |
| --- | --- | --- |
| Telnexa base exact-head CI | PASS | [run 34658149559](https://github.com/appolon1908-hue/telnexa/actions/runs/34658149559) |
| Telnexa candidate exact source/merge/private contract/security | PASS | [run 34691478919](https://github.com/appolon1908-hue/telnexa/actions/runs/34691478919), [private contract run 34691478925](https://github.com/appolon1908-hue/telnexa/actions/runs/34691478925), and [real Middleware GET contract run 34691478911](https://github.com/appolon1908-hue/telnexa/actions/runs/34691478911) |
| Telnexa base immutable release | FAIL | [run 34658149648](https://github.com/appolon1908-hue/telnexa/actions/runs/34658149648): Keycloak image contains critical CVE-2026-75595 in Netty 4.1.136.Final; fixed upstream version is not yet available in the pinned official Keycloak release used by the repository |
| Middleware candidate required CI | PASS on current head | [run 34691331306](https://github.com/appolon1908-hue/Middleware-/actions/runs/34691331306) passed on `f9bc648b49a2e69aae1d7a272cb392e65888b3a4`; [first-head run 34690948972](https://github.com/appolon1908-hue/Middleware-/actions/runs/34690948972) records the repaired type-check failure |
| Middleware protected trust | BLOCKED | [contract run 34690948907](https://github.com/appolon1908-hue/Middleware-/actions/runs/34690948907) and [trusted evidence run 34690948942](https://github.com/appolon1908-hue/Middleware-/actions/runs/34690948942) reject stale protected hashes. Exact transition hashes are recorded on PR 267; the candidate does not self-authorize them. |
| Keycloak candidate source and merge validation | PASS | [run 34690965263](https://github.com/appolon1908-hue/Keycloak/actions/runs/34690965263); bootstrap approval remains separate |
| Keycloak bootstrap | BLOCKED | [run 34690965256](https://github.com/appolon1908-hue/Keycloak/actions/runs/34690965256) returned `missing-independent-approval`, as designed |

## Gate ledger

| Gate | Status | Evidence or blocker |
| --- | --- | --- |
| `RELEASE_SOURCE_CERTIFIED` | `BLOCKED` | PR heads are unmerged; source lock, approvals, signed images and exact release tuple absent |
| `PROTECTED_CI` | `FAIL` | Middleware trust transition and Keycloak independent approval unresolved; exact Telnexa PR CI pending |
| `STAGING_CERTIFIED` | `BLOCKED` | candidate not deployed to staging |
| `CARRIER_CREDENTIALS` | `BLOCKED` | no approved DIDWW production SMPP credentials installed through OpenBao |
| `SENDER_DESTINATION_LIMITS` | `BLOCKED` | no owner-approved tenant, sender, non-USA destination, exact MPS/TPS or launch window supplied |
| `DLR_MO_CALLBACK_CONFIGURATION` | `BLOCKED` | source contract implemented; actual DIDWW callback values, mTLS identity, HMAC and tenant assignment absent |
| `KEYCLOAK_SECURITY` | `FAIL` | critical CVE-2026-75595 remains in the release scan; scan is not bypassed |
| `SIGNED_DIGEST_PINNED_IMAGES` | `BLOCKED` | no exact candidate API/Jasmin/relay/Keycloak digests or signature verification |
| `BACKUP_VERIFIED` | `PARTIAL` | encrypted local backup execution observed; candidate-specific SHA/encryption/archive evidence absent |
| `RESTORE_REHEARSAL` | `BLOCKED` | last recorded PASS was 2026-09-02, not this candidate |
| `ROLLBACK_REHEARSAL` | `BLOCKED` | source runbook exists; exact candidate rollback not rehearsed |
| `PRODUCTION_AUTHORIZATION` | `NOT_AUTHORIZED` | no change ID, owners, approved scope, limits, release SHA or time window supplied |
| `TRANSACTIONAL_POLICY` | `INACTIVE` | no authorization/policy row created; global deployment interlock remains false |
| `E2E_CANARY` | `BLOCKED` | no approved sender/recipient or carrier sandbox window; no live send attempted |
| `MT` | `BLOCKED` | no carrier evidence |
| `DLR` | `BLOCKED` | source tests pass; no carrier callback observed |
| `MO` | `BLOCKED` | source tests pass; no carrier inbound message observed |
| `IDEMPOTENCY` | `PARTIAL` | duplicate/conflict/replay source tests pass; carrier timeout/restart sandbox certification absent |
| `METERING` | `PARTIAL` | segment reservation/finalization source tests pass; carrier statement reconciliation absent |
| `STOP_SUPPRESSION` | `PARTIAL` | durable STOP and pre-provider suppression source tests pass; bounded carrier proof absent |
| `OBSERVABILITY` | `BLOCKED` | protected metrics and alerts exist, including policy denial, queue, circuit, unknown submission, unmatched event and billing drift signals; dashboard, missing-callback coverage and alert delivery tests absent |
| `KILL_SWITCH` | `PARTIAL` | source tests and runbook pass; live stop-new-sends rehearsal absent |
| `CONTROLLED_ROLLOUT` | `BLOCKED` | P0 remains closed; P1 has not started |
| `CAMPAIGN_MODE` | `DISABLED` | required and verified in source; no campaign authorization route exists |
| `SPF_DKIM_DMARC` | `NOT_APPLICABLE_SMS` | email authentication is outside the Telnexa SMS mission |

## Required next evidence

1. Merge reviewed OpenBao policy and provision scoped DIDWW connection,
   callbacks, throughput and Middleware identity values without logging them.
2. Obtain carrier and owner records for the exact tenant/account, senders,
   non-USA destinations, MPS/TPS, segment quotas, USD 2 ceiling, launch window,
   monitoring, escalation and rollback owners.
3. Complete independent review and protected trust maintenance; remediate the
   Keycloak CVE and make every exact-head release check green.
4. Build, sign and verify digest-pinned API, Jasmin, relay and fixed Keycloak
   images; update the source lock and deploy that exact tuple to staging.
5. Execute the bounded sandbox matrix: MT, DLR, MO, GSM-7, Unicode/UCS-2,
   multipart, throttling, provider timeout/read-back, replay, restart,
   STOP/suppression and carrier billing reconciliation.
6. Produce a fresh encrypted backup with SHA-256, isolated restore evidence and
   a timed rollback rehearsal that keeps callbacks and observability available.
7. Record security, compliance, billing and owner approvals, create the
   immutable authorization, then start P1 with one sender, one destination and
   low quotas. Do not expand a failing batch.

Until those steps complete, `LIVE_SMS_DELIVERY=false` and the only truthful
decision is `NOT_AUTHORIZED`.
