# Middleware database production release

The production authority is PostgreSQL 17.6 in `codestra-postgres-1`, database
`codestra_middleware`, with application role `mw_integration_api`. Production
images must be deployed by immutable digest and must identify the merged main
revision through OCI metadata and verified provenance.

## Pre-change gates

1. Require an encrypted local and off-host backup less than one hour old.
2. Retrieve the exact remote artifact, verify its checksum, and ensure PostgreSQL
   17 can list the archive before changing production.
3. Restore and migrate an isolated copy to the target Alembic head.
4. Start the immutable candidate against the isolated upgraded database and
   require `/healthz` and `/readyz` to return 200.
5. Require an independently approved image digest, migration plan, maintenance
   window, recovery policy, and change record.

## 0054 to 0056 rollback

Revisions 0055 and 0056 add tables and provide downgrades which drop them. Once
the new release has accepted writes, downgrade is data-destructive and is not an
approved production rollback. Stop writes, preserve the failed state, restore
the pre-change backup, deploy the previous immutable image, and verify health,
readiness, migration head, and public route contracts.

The protected `rollout-middleware` operator captures a transaction-consistent
custom-format dump, database owner, Alembic head, checksum, and validated
readiness-backup stamp before migration. The accepted `restore-test` evidence
must name that exact backup stamp. Dumps, checksum validation, and restore input
are streamed rather than buffered in operator memory. `rollback-middleware` stops the three
replaced Middleware writers, preserves a checksum-bound failed-state dump,
disables new database connections before terminating all remaining sessions,
and recreates the database with connection limit zero. It restores the
pre-change database as the PostgreSQL superuser, restores the captured
connection policy only after `pg_restore`, starts the captured images, and
refuses PASS until the prior migration head, image IDs, health, and fail-closed
flags read back.

## Authorization authority

`VICIDIAL_AUTHORIZATION_URL` on the private 8443 listener is required and uses
the protected `vicidial-mtls` CA/client certificate material. The listener must
not be publicly published. `WEBPHONE_ENDPOINT_ADAPTER_URL` on 8444 is optional
while all WebPhone and telephony provisioning feature flags are disabled; keep
it empty rather than retaining an unreachable stale endpoint.

## Shared-cluster recovery interlock

The cluster also serves Odoo, n8n, email, control-plane, and test/rehearsal
databases. Do not change `archive_mode`, archive commands, replication, or HA
topology until an accountable owner approves RPO/RTO, an encrypted independent
archive destination, retention, base-backup frequency, a single-writer/fencing
design, and a maintenance window. Never create two independent writable nodes.
