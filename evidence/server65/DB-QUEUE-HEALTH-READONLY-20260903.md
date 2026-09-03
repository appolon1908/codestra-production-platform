# Database and queue health read-only probes

Date: 2026-09-03
Target: `65.109.65.169`
Access: Docker exec of standard health clients only; no credentials printed or changed.

- `codestra-postgres-1`: `pg_isready` accepting connections
- `codestra-kong-kong-db-1`: `pg_isready` accepting connections
- `codestra-n8n-staging-postgres-1`: `pg_isready` accepting connections
- `codestra-redis-1`: `redis-cli ping` succeeded

These probes establish process-level connectivity only. They do not certify
authentication, restricted roles, schema/migration heads, persistence,
durability, queue leases, retries, dead letters, duplicate prevention, or
isolated restore.

DATABASE_PROCESS_HEALTH=PASS
QUEUE_PROCESS_HEALTH=PASS
DATABASES=FAIL
QUEUES=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
