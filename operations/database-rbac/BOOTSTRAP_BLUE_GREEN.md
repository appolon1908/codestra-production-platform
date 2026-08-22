# Bootstrap application-role blue/green replacement

PostgreSQL 17 does not permit the bootstrap role (OID 10) to lose superuser
authority. If an application login is OID 10, do not attempt an in-place
`ALTER ROLE`; replace the database cluster so a dedicated protected bootstrap
administrator is OID 10 and the restored application role is ordinary.

## Preconditions

- Exact platform merge SHA, CI, independent approval, and maintenance approval
  are recorded.
- A current encrypted backup and verified checksum exist.
- A full logical restore has passed on an internal-only candidate network.
- The application credential is reused from its existing mounted source; it is
  never printed or replaced by the cluster administrator credential.
- Candidate and old volumes are retained until post-cutover certification.
- All live delivery and telephony write controls remain false.

## Candidate construction

For each dedicated cluster independently:

1. Create a new, non-published PostgreSQL container using the same immutable
   major-version image and a new volume.
2. Initialize it with a dedicated protected bootstrap administrator named
   `codestra_cluster_admin`, using a root-readable password file in the existing
   secret store. Never initialize it with the application role.
3. Restore global roles and the application database from the fresh backup.
   Expected failures involving grants on PostgreSQL predefined roles must be
   reviewed; any role, database, schema, or application-object restore failure
   blocks cutover.
4. Run `reconcile_application_role.sql` as `codestra_cluster_admin` against the
   restored database.
5. Start the exact deployed application image against the candidate using the
   unchanged application credential source. Require health, readiness,
   persistent TEST_SYN read/write/rollback, migration-role, RLS, and negative
   privilege checks.

## Cutover

Cut over one database/application pair at a time. The pre-cutover candidate is
only a rehearsal and must never become authoritative from its point-in-time
backup. For the final cutover:

1. Quiesce this application's ingress at its edge and prove new requests are
   denied or held. Stop only that application and prove its database connection
   count is zero. Keep the old database running but quiesced; no writer may
   remain connected.
2. Create and checksum a new logical globals backup and application-database
   backup from the quiesced old cluster. Any new connection or checksum failure
   blocks cutover and requires the application to be restored on the old
   cluster.
3. Restore those final backups into a fresh candidate volume initialized with
   `codestra_cluster_admin`. Do not layer the final restore over the rehearsal
   candidate.
4. Apply `reconcile_application_role.sql`, then rerun the restore-integrity,
   role-negative, persistent TEST_SYN read/write/rollback, and migration-head
   checks against the final candidate while the production application remains
   stopped.
5. Stop the old database, attach the final candidate to the original private
   network alias, and start the application with its unchanged credential
   mount. This restart is a remediation cutover—not a restart-recovery test.
   Keep edge ingress quiesced until readiness, the persistent probe, and
   record-count reconciliation all pass. Only then restore ingress and begin
   the next pair.

Do not delete or reuse the old volume. If readiness or the persistent probe
fails, stop the candidate, restore the original database container/network
alias, start the application, verify it while ingress remains quiesced, then
restore ingress and record the rollback. Because the original
application was quiesced before the final backup and remains stopped through
the switch, the retained old volume and final backup represent the same
authoritative write boundary; do not accept traffic on both clusters.

## Required readback

For every application role require `oid <> 10`, `LOGIN`, `NOSUPERUSER`,
`NOCREATEDB`, `NOCREATEROLE`, and `NOBYPASSRLS`; no membership in owner or
migrator; zero owned application objects; and a healthy application connection
using the mounted application credential. The protected bootstrap account must
not be exposed through an application mount or public port.
