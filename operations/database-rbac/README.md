# Production PostgreSQL application-role remediation

This package separates application-data ownership from runtime login authority.
It must first be run against an isolated restore, then through the protected
release workflow, and only then during an approved production maintenance
window.

For each dedicated database cluster create:

- `<application>_data_owner`: `NOLOGIN`; owns the application database,
  application schemas, tables, sequences, views, and routines.
- `<application>_migrator`: `LOGIN NOINHERIT`; is the only member of the data
  owner role and is used only by controlled migrations.
- the existing application login: `LOGIN INHERIT`, direct runtime grants only,
  and no membership in either privileged role.

The SQL deliberately does not touch PostgreSQL catalogs or template databases.
Those objects were created under the bootstrap role at cluster initialization;
`allow_system_table_mods` remains disabled. The runtime login loses all
cluster-wide privilege and all ownership of application objects.

`runtime_create=true` is allowed only for applications whose current immutable
runtime executes `CREATE ... IF NOT EXISTS` during startup. It grants schema
creation inside that application's dedicated database and `CREATE` on its
application schemas—not cluster-level database creation, role creation,
cross-database access, RLS bypass, or ownership. Remove this compatibility grant
when runtime DDL has been moved into the protected migrator job.

Production execution requires a fresh backup, isolated rehearsal evidence,
protected merge SHA, exact checksums, and an approved maintenance window.
