# Database certification — 2026-09-02

```text
DATABASE_CERTIFICATION=FAIL_PENDING_PROTECTED_MERGE_AND_RUNTIME_REVALIDATION
BACKUP_AUTHORITY_PR=182
PREVIOUS_RUNTIME_BACKUP=PASS
PREVIOUS_RUNTIME_ISOLATED_RESTORE=PASS
PREVIOUS_STANDBY_LAG_METHOD=SUPERSEDED
CORRECTED_PRIMARY_TO_STANDBY_LAG_SOURCE=PREPARED_IN_PR
CORRECTED_SOURCE_INSTALLED=NO
CORRECTED_RUNTIME_BACKUP=NOT_RERUN
CORRECTED_RUNTIME_RESTORE=NOT_RERUN
PRODUCTION_BUSINESS_WRITES_ENABLED=NO
EXTERNAL_BUSINESS_EFFECTS=0
```

The previously captured runtime evidence proved that
`codestra-websocket-replica-postgres-1` was in recovery, had a streaming WAL
receiver, had a replay LSN, and had zero receive-to-replay lag. Review correctly
identified that receive-to-replay lag can be zero while both positions remain
behind the primary. That evidence therefore remains useful for receiver health
but is not sufficient for the production RPO claim.

PR #182 now requires comparison of the primary's current flushed WAL position
with the standby replay LSN. It also removes incomplete backup completion
directories, selects restore input only from checksum-verified PASS backups,
applies bounded verified local retention, publishes backup and restore metrics
independently, loads alert rules from Prometheus's mounted rules directory, and
verifies disposable restore container and volume deletion before recording zero
residual resources.

The corrected scripts and systemd units must merge through the protected
`release/production-activation` branch, be installed from the exact protected
merge, and then run a fresh encrypted/off-host backup plus isolated restore.
Only that new runtime evidence can change this database certification to PASS.
WAL retention remains seven days; certification-backup local retention defaults
to 30 days and is bounded from 7 through 365 days.
