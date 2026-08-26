# Odoo Call Follow-up Docker Rollback

## Rule

An image rollback is sufficient only when no module installation, upgrade,
schema change, or persistent data change occurred. After `--init` or
`--update`, restore the matching PostgreSQL backup and Odoo filestore
together. Do not attempt an in-place schema downgrade and do not uninstall
the addon as a production rollback strategy.

## Required evidence captured before release

- previous application Git SHA;
- previous image reference by `repository@sha256`;
- verified PostgreSQL backup ID;
- matching verified filestore backup ID;
- exact Compose files and project name;
- current Odoo database name;
- middleware event-retention state;
- rollback owner and approved change ID.

## Rollback sequence

1. Stop new completed-call delivery to Odoo at middleware while retaining
   events durably for replay.
2. Disable call-follow-up agent access if the Odoo web process is still
   reachable.
3. Stop all Odoo web, worker, cron, and migration containers.
4. Restore the pre-change PostgreSQL backup.
5. Restore the matching pre-change Odoo filestore.
6. Check out the recorded previous application SHA.
7. Set the previous immutable image digest.
8. Render and inspect the complete Compose configuration.
9. Start Odoo and wait for registry, web, bus, cron, database, and mail queue
   health.
10. Run synthetic CRM read-only and call-follow-up reconciliation checks.
11. Re-enable middleware delivery only after Odoo and reconciliation pass.
12. Record every command, timestamp, artifact ID, and operator.

Never start the previous application image against a database that has not
been restored when the failed release changed module schema or data.
