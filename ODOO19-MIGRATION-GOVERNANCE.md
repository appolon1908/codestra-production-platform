# Odoo 18 to Odoo 19 migration governance

Document state: `CONTROLLED_CANDIDATE_NOT_APPROVED`

This document defines the required control but is not effective until every
named owner below records approval. Codex prepared it and has not signed for
any person.

## Scope and baseline

- In scope: the self-hosted Odoo PostgreSQL database, matching filestore,
  Odoo 18 source recovery state, Odoo 19 Community target, four `codestra_*`
  modules, middleware and n8n staging contracts, reverse proxy, backups,
  monitoring, and VICIdial read-only integration boundaries.
- Excluded: the independently managed VICIdial database, live calls, carrier
  submissions, production messaging, payment capture, and production cutover.
- Odoo 19 Community revision: digest-pinned clean-test image recorded in the
  module test evidence.
- Enterprise revision: not applicable; the representative database reports no
  Enterprise code and no installed `web_enterprise`.
- Custom module baseline: `a48f12f355239e9bac725898eca6976aa0c55fa2`;
  clean-suite pin `3f2eff50254d62cb42531fe72e9d0be2cdb1a7d2`.
- Representative source pair:
  `/root/odoo19-representative-migration-20260723T210200Z/source-pair`.

## Data and integration controls

Migration must use a restored staging copy, never the live database. The
database and filestore must be captured in one quiesced consistency window,
verified by SHA-256, restored together, and retained for rollback. VICIdial
writes, external dialing, transfers, production callbacks, production n8n
workflows, WebRTC production routes, outbound email, SMS, WhatsApp, social
publishing, payments, and carrier submissions remain disabled. The historical
queue remains unchanged.

## Measurable acceptance

Acceptance requires: registry startup; admin and internal-user authentication;
representative attachments opening with matching digests; clean module install
and migrated-database upgrade; contacts, CRM, leads, activities, calls,
dispositions, callbacks, recording metadata, DNC, consent, audit, reports,
scheduled actions, multi-company and access-control checks; staging-only
middleware/n8n tests; restart persistence; zero critical or high defects; and a
complete pre-migration database/filestore rollback with measured recovery time.

Severity definitions: critical permits data loss, unauthorized external action,
or total service loss; high breaks a mandatory workflow or security boundary;
medium has a controlled workaround; low is cosmetic or low-impact. Critical and
high defects block acceptance.

## Authorities and responsibilities

| Authority | Required person and contact | Responsibility | Recorded decision |
|---|---|---|---|
| System Owner | NOT PROVIDED | Scope, exceptions, final governance approval | NOT RECORDED |
| Technical Acceptance Owner | NOT PROVIDED | Migration and technical test acceptance | NOT RECORDED |
| Business Acceptance Owner | NOT PROVIDED | Business workflow acceptance | NOT RECORDED |
| Security Acceptance Owner | NOT PROVIDED | Security and secret-remediation acceptance | NOT RECORDED |
| VICIdial Acceptance Owner | NOT PROVIDED | Read-only integration acceptance | NOT RECORDED |
| Email and Marketing Acceptance Owner | NOT PROVIDED | Delivery-safety acceptance | NOT RECORDED |
| Production Deployment Approver | NOT PROVIDED | Cutover authority | NOT RECORDED |
| Rollback Decision Owner | NOT PROVIDED | Rollback invocation and rehearsal acceptance | NOT RECORDED |

Exceptions require a written owner, rationale, bounded duration, compensating
control, expiry, and System Owner plus Security Owner approval. Evidence must be
sanitized, checksum-verifiable, and contain no production data or secrets.
Production cutover remains prohibited until the exact separately required owner
authorization is recorded.

