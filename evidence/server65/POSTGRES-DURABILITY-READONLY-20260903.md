# PostgreSQL durability read-only probe

Date: 2026-09-03
Target: `65.109.65.169` primary PostgreSQL container
Access: Docker exec with read-only `SHOW` statements; no secret values.

- `max_connections`: `100`
- `fsync`: `on`
- `synchronous_commit`: `on`
- `full_page_writes`: `on`
- `wal_level`: `replica`

These settings are consistent with durable WAL-backed operation. They do not
prove backups, replication/archiving, restricted application roles, schema
migrations, indexes/constraints, pool limits, or isolated restore. Kong's
database container does not expose a `postgres` role to the bounded probe;
role ownership remains unverified.

POSTGRES_DURABILITY_SETTINGS=PASS
DATABASE_ROLE_ISOLATION=UNVERIFIED
DATABASES=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
