# Production database certification authority

This package owns the fail-closed encrypted backup and isolated restore
certification for the production database set. Runtime credentials remain in
root-controlled environment files and are never stored here.

The WebSocket backup source is the streaming standby. The backup refuses an
unhealthy receiver, a server not in recovery, missing replay state, or replay
lag beyond the configured byte policy. Lag is measured from the primary's
current flushed WAL position to the standby's replay LSN; receive-to-replay lag
alone is not accepted as proof that the standby is current. Provisioning backup
always uses the production state volume mounted by the production container;
the retired volume is rollback evidence and is never selected.

Failed backup attempts are removed from the timestamped completion namespace.
Restore selects the newest candidate only after verifying `DATABASE_BACKUP=PASS`,
encryption/checksum status, the encrypted artifact checksum, and the
status-evidence checksum. A failed newer attempt therefore cannot hide the
newest valid recovery point.

Successful backups enforce local retention through
`CODESTRA_DATABASE_BACKUP_RETENTION_DAYS`, which defaults to 30 days and is
bounded from 7 through 365 days. Only completed, checksum-verified backup
directories are eligible for pruning. Off-host retention remains controlled by
the approved independent backup destination.

The systemd timers serialize execution, enforce bounded runtime, publish
freshness and replication metrics after success, and retain encrypted,
checksummed off-host evidence. Both units invoke the metrics exporter from this
package and grant write access only to the Node Exporter textfile directory and
their required evidence paths. Restore rehearsals use isolated disposable
databases and verify container and volume removal before recording
`RESTORE_RESIDUAL_RESOURCES=0`.

Prometheus loads the database certification rules from
`operations/monitoring/rules/database-certification.rules.yml`, which is inside
the monitoring stack's mounted rules directory.

The root ext4 filesystem reserve was changed on 2026-09-02 from 5% to 0.5%.
This exposed capacity already present on `/dev/md2`; it deleted no data and
retains approximately 2.2 GiB for UID 0. Rollback is `tune2fs -m 5 /dev/md2`
after first proving sufficient free blocks. The production warning threshold
remains unchanged.
