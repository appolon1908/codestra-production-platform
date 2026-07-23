# Odoo 18 → 19 representative migration governance

Status: `DRAFT_AWAITING_OWNER_ASSIGNMENT_AND_APPROVAL`

This document is a fail-closed change-control form. Blank approval fields are
intentional and must be completed by the accountable humans. Preparation of
this form is not approval to submit a database, migrate, cut over, or activate
production traffic.

## Change record

| Field | Required value |
|---|---|
| Change ID | |
| Official Odoo upgrade request/ticket | |
| Covered subscription/contract reference | |
| Source backup identifier | `/root/odoo19-representative-migration-20260723T210200Z/source-pair` |
| Source database SHA-256 | `877f447fb1510c03f729705e2b7238d3d9948fe9fa756e157ee3a9f6c7659e16` |
| Source filestore SHA-256 | `086b6cfaf79d5b5773dcab06d42bdf571ac7ae8f3362ab7efbc8c8be37987fa7` |
| Exact custom-addons commits | Odoo 18 capture: `e1b8ca76955185b7e9609cf501bfea1dfdeb61e6` plus captured dirty-tree manifest; Odoo 19 port: `a48f12f355239e9bac725898eca6976aa0c55fa2`; test pin: `3f2eff50254d62cb42531fe72e9d0be2cdb1a7d2` |
| Migration window start | |
| Migration window end | |
| Timezone | |

## Accountable owners

| Responsibility | Named owner | Approval/signature | UTC timestamp |
|---|---|---|---|
| Migration execution | | | |
| Business acceptance | | | |
| Rollback decision/execution | | | |
| Security acceptance | | | |
| Database/filestore custody | | | |
| Odoo subscription/upgrade request | | | |

## Preconditions

Every item must be checked and linked to evidence before migration starts.

- [ ] The database and filestore pair passed the isolated Odoo 18 application
  restore, authenticated admin and non-admin login, attachment-open, restart,
  and recovery drill.
- [ ] The official Odoo upgrade provider confirmed entitlement for this
  database and issued a request/ticket reference.
- [ ] The approved migration window is active.
- [ ] All accountable owners are named and available.
- [ ] A fresh immutable pre-migration database dump and matching filestore
  archive exist, with SHA-256 checksums.
- [ ] Exact Odoo 18 and Odoo 19 images/source revisions are pinned.
- [ ] Exact custom and third-party add-on revisions are pinned.
- [ ] The migration environment is isolated from production networks and all
  email, SMS, payment, callback, VICIdial, n8n production, and external-delivery
  capabilities are disabled.
- [ ] Rollback resources and the known-safe Odoo 18 image are locally
  available.
- [ ] Evidence storage, redaction, and retention locations are approved.

## Acceptance criteria

All mandatory criteria require evidence after a complete-stack restart.

| Area | Mandatory result |
|---|---|
| Upgrade provenance | Official upgraded database checksum and ticket match |
| Registry/modules | Registry initializes; all required modules install/upgrade without errors |
| Database integrity | Constraints, foreign keys, XML IDs, and scheduled actions validate |
| Authentication | Administrator and non-administrator staging users authenticate |
| Security | Groups, record rules, multi-company, agent, supervisor, and portal isolation pass |
| Core records | Contacts, users, CRM leads, activities, and campaigns reconcile |
| Call-center records | Calls, dispositions, callbacks, recording metadata, DNC, consent, and audit reconcile |
| Attachments | Representative files from multiple models open with expected MIME type and size |
| Integrations | Middleware and n8n staging-only contract tests pass; all production delivery flags remain false |
| Reports | Required reports render and reconcile to source records |
| Restart | PostgreSQL and Odoo 19 restart; critical checks repeat successfully |
| Evidence | Logs, durations, checksums, commits, images, and test outputs are complete and sanitized |

Acceptance decision:

- [ ] `ACCEPT`
- [ ] `REJECT_AND_ROLL_BACK`

Business acceptance owner signature: ____________________

Security approver signature: ____________________

Decision timestamp UTC: ____________________

## Stop conditions

Stop and invoke rollback on any of the following:

- official upgrade provenance or checksum cannot be verified;
- registry or required module fails;
- database/filestore mismatch or unreadable mandatory attachment;
- authentication or authorization isolation failure;
- unreconciled loss/duplication of mandatory business records;
- any production-capable integration flag becomes enabled;
- any unexpected production network access, external delivery, call, or write;
- acceptance window expires or an accountable owner becomes unavailable.
