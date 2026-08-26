# Odoo and n8n production preflight

`production-preflight.sh` is a read-only preparation gate for the Odoo and n8n
production change. Run it as root from a checkout of the exact approved platform
commit:

```bash
operations/odoo-n8n/production-preflight.sh
```

`ODOO_N8N_READY_FOR_CHANGE_WINDOW=YES` means the runtime, private network,
database-role, schema/module, route, middleware-connectivity, and capacity checks
passed. `PENDING` gates may remain before the approved window. It does **not**
certify PITR or authorize a PostgreSQL restart.

The shared PostgreSQL validator remains the only activation authority. Continue
only when it returns `SHARED_POSTGRES_CUTOVER_GO=YES`. The in-window procedure
must then create fresh encrypted local/off-host backups, verify remote retrieval,
activate WAL archiving, create and restore a physical base backup, and prove PITR
for both `codestra_odoo` and `codestra_n8n` within the approved RPO/RTO.

Do not use `operations/readiness/codestra-local-consistency-backup.sh` as change
authority. It pauses application containers and contains a historical waiver and
timezone contract. It may only be replaced or used through a separately reviewed
change. The shared PostgreSQL recovery package is authoritative for this cutover.

After PITR passes, Odoo recreation additionally requires its separate approved
maintenance window, a fresh Odoo database+filestore pair, semantic Compose drift
of zero, the approved immutable image digest, and rollback precheck. n8n requires
its database+state-volume pair, immutable digest lock, workflow safety policy,
and rollback precheck. Neither service may publish its application or database
ports directly.
