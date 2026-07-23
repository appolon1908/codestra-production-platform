# Odoo 19 representative migration rollback rehearsal

Status: `DRAFT_AWAITING_OWNER_ASSIGNMENT_AND_APPROVAL`

This form defines the isolated rollback test. It does not authorize a
production rollback or cutover.

## Authorization

| Field | Required value |
|---|---|
| Change ID | |
| Migration evidence package | |
| Pre-migration checkpoint identifier | |
| Rollback owner | |
| Acceptance owner | |
| Approved start/end/timezone | |
| Rollback authorization/signature | |

## Procedure

1. Record the upgraded database and filestore checksums and stop isolated
   Odoo 19.
2. Preserve migration logs and the failed/accepted upgraded state.
3. Restore the immutable pre-migration Odoo 18 database dump into a fresh
   disposable PostgreSQL service.
4. Restore the matching pre-migration filestore to the exact database-keyed
   Odoo filestore path.
5. Start the pinned known-safe Odoo 18 image with the frozen add-on revisions.
6. Keep cron-driven external delivery disabled and the network isolated.
7. Verify administrator and non-administrator authentication.
8. Open representative attachments from multiple models and verify MIME type,
   size, and readability.
9. Reconcile contacts, CRM leads, users, activities, calls, dispositions,
   callbacks, DNC, consent, audit, and scheduled jobs.
10. Confirm `SEND_EVENTS=false`,
    `PRODUCTION_CALLBACKS_ENABLED=false`, `VICIDIAL_WRITES_ENABLED=false`,
    `EXTERNAL_DIAL_ENABLED=false`, and
    `N8N_PRODUCTION_WORKFLOWS_ENABLED=false`.
11. Restart PostgreSQL and Odoo 18, then repeat login and attachment checks.
12. Record rollback start, service-ready, validation-complete, and total
    recovery durations.
13. Stop and remove the disposable environment after evidence capture.

## Required results

| Check | Result/evidence |
|---|---|
| Pre-migration database checksum | |
| Pre-migration filestore checksum | |
| Database restore | |
| Filestore restore | |
| Registry initialization | |
| Admin/non-admin authentication | |
| Multi-model attachment access | |
| Business-record reconciliation | |
| Scheduled external deliveries disabled | |
| Post-restart validation | |
| Rollback duration | |
| Recovery validation duration | |

Rollback rehearsal decision:

- [ ] `PASS`
- [ ] `FAIL`

Rollback owner signature: ____________________

Acceptance owner signature: ____________________

Decision timestamp UTC: ____________________
