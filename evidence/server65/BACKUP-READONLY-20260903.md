# Server 65 backup read-only audit

Date: 2026-09-03
Target: `65.109.65.169`
Access: existing `codestra-app` / `codestra-admin`; filesystem metadata only.

## Findings

- `/srv/codestra/backups`: absent
- `/srv/codestra/evidence`: absent
- `/home/codestra-admin/backups`: absent
- A Caddy archive exists at `/var/backups/caddy/` with a checksum sidecar and
  manifest, timestamped 2026-09-02.
- Archive, sidecar, and manifest are mode `0600`, owned by `root:root`.
- The approved service account cannot read the archive or verify its checksum;
  the bounded checksum attempt returned `Permission denied`.
- An off-host destination marker exists, but the success marker is absent.

This proves only that a root-owned Caddy backup artifact exists. It does not
prove complete application/database backup coverage, off-host transfer,
encryption-key custody, retention, or isolated restore.

BACKUPS=FAIL
OFF_HOST_BACKUP=FAIL
RESTORE=FAIL
RPO=UNMEASURED
RTO=UNMEASURED
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
