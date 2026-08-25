# 14 — Databases (Step 18)

Scope: codestra-app host (10.40.0.1) only, per confirmed audit scope. Read-only inspection via `docker inspect`/`docker exec`/`ss`. No data modified, no credentials printed.

## Inventory (live containers only)

| Container | Engine | DB/Role | Network | Host port exposed? |
|---|---|---|---|---|
| codestra-postgres-1 | Postgres 17.6 (alpine) | ~29 databases, role `postgres` (superuser) | codestra_backend | No |
| codestra-kong-kong-db-1 | Postgres 17 | db `kong`, role `kong` | codestra-kong_kong_backend | No |
| codestra-identity-identity-db-1 | Postgres 17 | db `keycloak`, role `keycloak` | codestra-identity_identity_db | No |
| codestra-sms-api-postgres-1 | Postgres 17-alpine | db `codestra_sms`, role `codestra_sms` | codestra_sms_data | No |
| codestra-reseller-portal-postgres-1 | Postgres 17-alpine | db `reseller_portal`, role `reseller_portal` | codestra_backend | No |
| codestra-websocket-gateway-postgres-1 | Postgres 16-alpine | db `codestra_realtime`, role `codestra_realtime` | codestra_backend | No |
| codestra-middleware-staging-postgres-1 | Postgres 17 | staging | codestra-middleware-staging_backend | No |
| codestra-n8n-staging-postgres-1 | Postgres 17 | staging | codestra-n8n-staging_backend | No |
| codestra-odoo-staging-postgres-staging-1 / odoo19-* staging DBs | Postgres 17 | staging | per-stack isolated networks | No |
| codestra-identity-staging-identity-db-staging-1 | Postgres 17 | staging | isolated | No |
| codestra-redis-1 / middleware-staging-redis / n8n-staging-redis | Redis | cache/queue | codestra_backend (shared) | No |
| codestra-backup-1 | Postgres 17.6 image, **no server process running** | not a database — see DB-3 | codestra_backend | No |

`ss -tlnp` confirms zero postgres/redis ports bound to the host — all DB access is confined to internal docker bridge networks.

## Findings

### DB-1 — P2 — Shared production+test/rehearsal Postgres cluster
**Component:** codestra-postgres-1
**Observed evidence:** `SELECT datname FROM pg_database` returns ~29 databases in one cluster, mixing apparent production databases (`codestra_odoo`, `codestra_middleware`, `codestra_n8n`, `control_plane`, `beyvra_email`, `email_reseller`) with clearly transient ones (`codestra_odoo_test`, `codestra_n8n_restore_test`, `codestra_odoo_fresh_20260804`, `breero_restore_codestra_middleware_20260813`, `codestra_odoo_upgrade_verify_20260804`, `publisher_rollback_test`, `codestra_call_workspace_test_20260822`, etc.).
**Expected state:** production databases isolated in a cluster (or at minimum a role/ACL boundary) separate from ad-hoc test/rehearsal/rollback databases.
**Current state:** all share one Postgres instance and the `postgres` superuser role.
**Risk:** a rehearsal/restore operation (e.g. `DROP DATABASE`, disk exhaustion, connection-limit exhaustion, an errant `ALTER SYSTEM`) against a test DB can degrade or take down the shared instance that also serves production Odoo/middleware/n8n.
**Files/config:** container `codestra-postgres-1`, network `codestra_backend`.
**Recommended fix:** move production databases to a dedicated cluster/role set; retire or move rehearsal/test databases to a disposable instance; add a max-database-age or naming-convention lint to prevent silent accumulation.
**Test required:** verify no application depends on cross-database access within the shared cluster before splitting.
**Rollback:** none needed (this is a hygiene/isolation recommendation, not an active change).
**Repo:** appolon1908-hue/codestra-production-platform. **Suggested branch:** `fix/postgres-cluster-isolation`.

### DB-2 — P2 — No in-transit encryption on internal Postgres connections; broad pg_hba scope
**Component:** codestra-postgres-1, codestra-kong-kong-db-1 (and presumably other Postgres containers, sampled two)
**Observed evidence:** `SHOW ssl;` → `off` on both. `pg_hba.conf` on codestra-postgres-1: `host all all all scram-sha-256` — password auth is enforced (not `trust`) but the rule is not scoped to specific source subnets/roles/databases.
**Expected state:** TLS enabled for Postgres connections even on internal networks (defense-in-depth), and `pg_hba.conf` rules scoped to the specific application subnet/role/database rather than `all all all`.
**Current state:** plaintext internal connections; broad host-based-auth rule.
**Risk:** any container that can reach the `codestra_backend` bridge network (not just the intended application containers) can attempt authentication against any database with any role; traffic between application and DB is unencrypted within the docker network.
**Mitigating factor:** the bridge network is not reachable from outside the host, and password auth (scram-sha-256) is required — this is not an open/trust configuration.
**Recommended fix:** enable `ssl = on` with a locally-issued cert for internal Postgres, and narrow `pg_hba.conf` entries to the actual application container subnets/roles per database.
**Test required:** confirm application connection strings tolerate `sslmode=require` before flipping the server flag.
**Rollback:** revert `ssl` setting / pg_hba.conf from backup.
**Repo:** appolon1908-hue/codestra-production-platform. **Suggested branch:** `fix/postgres-internal-tls`.

### DB-3 — P3 — `codestra-backup-1` container name is misleading
**Component:** codestra-backup-1
**Observed evidence:** container has PG 17 tooling installed (`PG_VERSION=17.6` etc. in image env) but **no postgres server process is running** — no listening socket, `psql` connection fails with "No such file or directory". It is used to *run* backup/restore utility commands (`pg_dump`/`pg_basebackup`/`pg_restore`), not as a live database or standby replica.
**Expected state:** name/documentation should make clear this is a backup-tooling utility container, not a hot standby.
**Risk:** during an incident, an operator could mistake `codestra-backup-1` for a live standby DB and waste time, or assume replication exists when it doesn't.
**Recommended fix:** rename to something like `codestra-backup-toolbox-1`, or document its role in `docs/`.
**Repo:** appolon1908-hue/codestra-production-platform. **Suggested branch:** `docs/backup-container-naming`.

### DB-4 — P2 — AI-agent / admin database access boundary not fully verified
**Component:** AI-related services referenced in Odoo module list (`codestra_ai_core`, `codestra_ai_qualification`, `codestra_ai_call_audit`, `codestra_ai_realtime_assistant`, `codestra_ai_review`) and any agent-facing endpoints.
**Observed evidence:** none of these appeared as separate containers with directly-mounted database credentials in the containers sampled; they appear to be Odoo addons running inside the existing `codestra-odoo-1`/staging Odoo processes, which already hold the Odoo DB credential by necessity.
**Current state:** UNVERIFIED — did not have time within this pass to trace every AI-related code path to confirm none of them is handed elevated/administrative DB credentials beyond the standard Odoo application role.
**Risk:** if unverified, an AI-facing endpoint with DB-admin-level credentials would be a P0.
**Recommended fix:** a dedicated follow-up pass grepping AI-related addon code and its Odoo record rules/ACLs for the DB role it runs as, and confirming it is the standard scoped Odoo application role, not `postgres` superuser.
**Repo:** appolon1908-hue/codestra-production-platform. **Suggested branch:** `audit/ai-db-privilege-verification`.

## Architectural boundary verification (mission-critical check)

**Odoo → direct VICIdial database writes:** Searched the actually-deployed Odoo addon source (`/opt/codestra/releases/odoo-addons/91e22ef.../codestra_vicidial_connector`, `codestra_vicidial_crm`, `codestra_vicidial_recording` — the paths bind-mounted into the live `codestra-odoo-1` container) for `pymysql`, `mysql.connector`, `MySQLdb`. **Zero matches.** `codestra_vicidial_connector` implements a generic import/normalize/preview/apply pattern, not a live raw DB link. **No violation found** (static analysis of deployed code only — does not prove absence of a network-level MySQL client call outside grepped patterns).

**n8n → direct VICIdial database writes:** Cloned `/opt/codestra/n8n-workflows-authoritative.git` (the authoritative workflow source) to a temp dir and enumerated every n8n node type used across all workflow JSON: only `code`, `cron`, `errorTrigger`, `executeWorkflow(Trigger)`, `httpRequest`, `if`, `manualTrigger`, `respondToWebhook`, `scheduleTrigger`, `stopAndError`, `switch`, `webhook`. **No `mysql` (or any database) node type is used anywhere.** n8n workflows referencing "vicidial" only use the string `vicidial_lead_id` as a JSON field name inside `httpRequest`/`code` nodes — not a database connection. **No violation found.**

**Browser → database access:** no database port is published to the host or, by extension, externally (confirmed via `ss -tlnp` and `docker port` — all DB containers show no host binding). **No violation found.**

**AI → database administrative access:** see DB-4 above — **UNVERIFIED**, not confirmed clean.

## Positive controls observed
- Redis requires authentication (`requirepass` set; unauthenticated `PING`/`CONFIG GET` both return `NOAUTH`).
- Every non-shared service (Kong, Keycloak/identity, SMS, reseller-portal, websocket-gateway realtime) runs its own dedicated Postgres container, own docker network, and own non-superuser role scoped to one database — good micro-segmentation, in contrast to DB-1 above.
- No database port is exposed beyond the host's internal docker networks.

## Unverified / out of time-budget for this pass
- Full migration state (Odoo `ir_module_module` versions, Alembic version tables) — not queried to avoid any risk of touching production DB state; recommend a dedicated read-only pass.
- Backup timestamp/restore-evidence verification for `codestra-postgres-1` specifically (Step 21 territory — see that report for VICIdial-side backup evidence, which does show daily backups under `/srv/codestra-backups/vicidial/`).
