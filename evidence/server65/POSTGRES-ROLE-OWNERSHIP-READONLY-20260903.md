# PostgreSQL role and database ownership read-only audit

Date: 2026-09-03
Target: `65.109.65.169` primary PostgreSQL
Access: read-only SQL as the database administrator; role names/flags only.

## Login-role read-back

All named application login roles observed (`middleware_app`, `control_plane_app`,
`n8n_app`, `odoo_app`, `email_reseller_app`, provider/worker roles, and
monitoring roles) have `rolsuper=false`, `rolcreaterole=false`, and
`rolcreatedb=false`. The `codestra_shared_backup` role has replication enabled;
its operational scope requires separate review. Only the built-in `postgres`
role is superuser.

## Database ownership

Primary production databases are owned by restricted roles:

- `codestra_middleware` → `middleware_app`
- `codestra_middleware_appolon` → `appolon_middleware_api`
- `control_plane` → `control_plane_app`
- `email_reseller` → `email_reseller_app`
- `codestra_n8n` → `n8n_app`
- `codestra_odoo` → `odoo_app`
- `beyvra_email` → `beyvra_email`

The same PostgreSQL instance also contains numerous test, restore, rehearsal,
candidate, and upgrade databases, several owned by `postgres`. This clutter
prevents a clean production database-ownership certification until lifecycle
and isolation are proven.

DATABASE_ROLE_ISOLATION=PARTIAL
DATABASES=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
