# Rollback runbook

Rollback is restoration, never an in-place downgrade: stop migrated services;
isolate the migrated database and filestore; restore the pre-cutover database,
matching filestore, source/Enterprise/custom revisions, configuration, proxy,
cron, and VICIdial integration state; start PostgreSQL and source-version Odoo;
verify registry, admin/internal login, attachments, critical workflows,
fail-closed flags, and monitoring; record duration and obtain rollback-owner
approval.

