# Odoo database/filestore paired restore

Production persistence is database `codestra_odoo` plus the content-addressed filestore under Odoo's effective data directory. A pair is accepted only when its `BACKUP_ID` matches, its outer SHA-256 manifest passes, every database `store_fname` exists, each referenced object's SHA-1 equals `ir_attachment.checksum`, and ownership matches the recorded Odoo UID/GID.

The isolated PostgreSQL role must be named `odoo_app` because the reviewed Odoo configuration fixes `db_user=odoo_app`. The isolated database is `codestra_odoo_restore`, and the restored filestore directory must use that same name. The internal Docker network must provide PostgreSQL alias `postgres` because the reviewed configuration fixes `db_host=postgres`.

The rehearsal network must be Docker `internal=true`, use a collision-checked subnet, publish no ports, and mount no production secrets or identities. Start Odoo with `--max-cron-threads=0`, workers disabled, database listing disabled, and an exact restore database filter. Verify `/web/health` only from inside the container. An isolated secret unique to the rehearsal is mounted read-only and removed with the rehearsal resources.

Before cleanup, export aggregate attachment counts and an attachment map containing only content-addressed `store_fname` and checksum values. Run `validate_odoo_filestore_pair.py`; preserve orphan filenames for classification and never delete them automatically. Record repository materialization time, database import time and application-health time as the measured RTO.
