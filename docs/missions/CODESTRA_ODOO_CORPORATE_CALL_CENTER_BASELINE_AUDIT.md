# Codestra Odoo Corporate Call Center Baseline Audit

Date: 2026-08-23

Authoritative specification: [PR #93](https://github.com/appolon1908-hue/codestra-production-platform/pull/93), pinned for this audit to immutable commit [`7826b9e95d61e4ac9fac65c50d0084567c0f3fff`](https://github.com/appolon1908-hue/codestra-production-platform/commit/7826b9e95d61e4ac9fac65c50d0084567c0f3fff), `docs/missions/CODESTRA_ODOO_CORPORATE_CALL_CENTER_FULL_CODEX_MISSION.md`

## Baselines audited

| Repository | Protected target | Audited commit | Protection observed |
|---|---|---|---|
| `appolon1908-hue/codestra-production-platform` | `release/production-activation` | `e9ed96ee9df258630d8c18b854c3b5a5a6003ec7` | Required `validate`, strict current-head checks, one approval, last-push approval, stale-review dismissal, administrators included |
| `Codestra-SRL/codestra-odoo-addons` | `main` | `cd17270e48ed07db060b528366a728f5c0c75a6d` | Required `validate` and `exact-head-gates`, strict current-head checks, one approval, last-push approval, stale-review dismissal, administrators included |

The live working directory named in `AGENTS.md` was not used for development. It was 89 commits behind its remote and contained extensive existing tracked and untracked operator work. Two clean, isolated Git worktrees were created from the protected remote baselines. No production configuration, database, provider, VICIdial, firewall, feature flag, or live service was changed during this audit.

## Baseline validation

| Check | Result | Evidence |
|---|---|---|
| Platform Python suite | PASS | `559 passed, 9 subtests passed in 60.94s` from `pytest -q` |
| Odoo Python source compilation | PASS | `python3 -m compileall -q call_center_* codestra* ci_addons` |
| Odoo XML parsing | PASS | All tracked XML outside `.git` parsed with `xml.etree.ElementTree` |
| Odoo CSV parsing | PASS | All tracked CSV outside `.git` parsed with Python's CSV reader |
| Odoo fresh install and module tests | NOT_TESTED | Must run in the protected PR `validate` job and an isolated local PostgreSQL/Odoo test environment |
| Odoo upgrade | NOT_TESTED | Must run in the protected PR `validate` job and against an approved sanitized upgrade fixture |
| Backup and isolated restore | BLOCKED | Requires backup owner, approved storage, encrypted backup execution, and isolated restore environment |
| Provider certification | BLOCKED | Requires independent Klyrow, Telnexa, and PSTN/provider approvals; no provider gate was opened |
| Browser screen-pop certification | NOT_TESTED | Requires isolated staging, authorized browser fixtures, and certification evidence |
| Production canary and soak | BLOCKED | Requires merged immutable release, independent approval, staging certification, maintenance tuple, backups, restore and rollback rehearsal |

## Existing implementation

The Odoo repository already contains useful foundations that must be preserved and extended:

- `codestra_vicidial_crm`: read-only VICIdial CRM projection, event ingestion, call/agent/campaign models, webhook idempotency, reconciliation, permissions and tests.
- `call_center_core`: business units, roles, tenant scoping, audit, feature flags, calling-hours policy, skills and canonical statuses.
- `call_center_campaign`: campaign lifecycle, mapping, scripts, pipeline, transactional outbox, result inbox and integration APIs.
- `call_center_compliance`: consent, DNC/suppression, calling-window and eligibility controls.
- `call_center_orchestration`: provisioning requests, callbacks and lead-import orchestration.
- `codestra_integration_hub`: event, delivery, idempotency, dead-letter, mapping and audit foundations.
- `codestra_identity_provisioning`: coordinated identity, extension and mailbox provisioning with safety flags.
- `codestra_telephony_bridge`: desired telephony state, transfer requests, result ingestion and reconciliation.
- `codestra_campaign_crm_os`, `codestra_appointments`, `codestra_daily_reporting` and `codestra_analytics_reporting`: campaign operations, callbacks and initial reporting capabilities.
- The platform repository already contains protected deployment governance, control-plane services, Kong/Keycloak contracts, VICIdial adapter code, monitoring, backup/rollback operations and fail-closed feature gates.

These components are not equivalent to mission completion. In particular, the exact canonical models `codestra.cc.interaction`, `codestra.cc.call.leg`, `codestra.cc.event`, `codestra.cc.wrapup`, `codestra.qa.evaluation`, and `codestra.provisioning.job` are absent. The mission permits an equivalent reviewed structure, but the current source has overlapping legacy concepts without a documented compatibility map proving equivalence.

## Principal gaps

1. A versioned compatibility map and restartable migrations are required before introducing the canonical interaction schema. Existing external IDs, VICIdial calls, CRM links, callbacks, audit and provisioning records must remain valid.
2. The unified interaction/call-leg model, mandatory wrap-up workflow, customer 360 timeline and responsive agent desktop are not complete.
3. Campaign-specific dispositions, versioned configuration publishing and rollback are partial and spread across modules.
4. QA, supervisor live operations, workforce, client operations, revenue assurance, case management, training, client portal and dedicated data-quality review are missing or materially incomplete.
5. The canonical `/v1/contact-center/` OpenAPI surface and all specified authorization-negative tests are incomplete.
6. The repository has extensive unit coverage, but migration interruption, sanitized upgrade, browser, accessibility, 150-session load, 50-event/s load, recovery and provider certification evidence remain absent.
7. PR #93 itself is not yet mergeable: its `validate` workflow failed on trailing Markdown whitespace and it still requires independent approval. This audit treats its contents as authoritative but does not bypass either gate.

## Protected PR sequence

Each tranche starts from the current protected target, uses a dedicated branch, runs repository CI, resolves every review thread, and requires an independent approval of the exact final head. Later tranches must rebase or merge the updated protected baseline and may not self-declare an upstream gate satisfied.

1. Baseline audit, mission traceability, and the tested canonical contact-center event-envelope contract (this change).
2. Canonical core schema, compatibility map, restartable migrations, ACLs and negative tenant tests.
3. Reliable event API, inbox/outbox semantics, OpenAPI contracts and authorization tests.
4. Agent desktop, screen-pop, interaction timeline and mandatory wrap-up.
5. Campaign configuration publishing, dispositions, customer 360 and rollback versions.
6. Supervisor, QA and compliance controls.
7. Workforce, client operations, onboarding, training, case management and data quality.
8. Revenue assurance, analytics and client portal.
9. Identity, mailbox, omnichannel and allowlisted automation completion, with all production provider flags remaining false.
10. Security, migration, load, accessibility and recovery certification.
11. Immutable release, SBOM, provenance and isolated staging. This cannot start before protected merges and exact-head approvals.
12. Separately approved production canaries and channel-by-channel soak. Email, SMS, callbacks and PSTN dialing remain independently gated.

## Safety status

All production activation and provider gates remain unchanged. No production readiness item is marked `PASS` solely from source inspection. Backup, restore, independent approval, immutable release, staging, rollback, canary and soak items remain `BLOCKED` or `NOT_TESTED` until their required evidence exists.
