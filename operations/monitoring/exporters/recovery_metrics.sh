#!/usr/bin/env bash
set -euo pipefail
umask 022

backup_root=${CODESTRA_BRAIN_BACKUP_ROOT:-/opt/codestra/backups/brain-certification}
restore_root=${CODESTRA_BRAIN_RESTORE_ROOT:-/opt/codestra/evidence}
output=${CODESTRA_RECOVERY_METRICS_OUTPUT:-/var/lib/node_exporter/textfile_collector/codestra_recovery.prom}

latest_backup=$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' -printf '%f\n' | sort | tail -1)
latest_restore=$(find "$restore_root" -mindepth 1 -maxdepth 1 -type d -name 'brain-restore-20*T*Z' -printf '%f\n' | sort | tail -1)
test -n "$latest_backup" && test -n "$latest_restore"
backup_status=${backup_root}/${latest_backup}/STATUS.txt
restore_status=${restore_root}/${latest_restore}/RESTORE-RESULT.txt
grep -qx 'BACKUP_STATUS=PASS' "$backup_status"
grep -qx 'ENCRYPTED=PASS' "$backup_status"
grep -qx 'DATABASE_RESTORE=PASS' "$restore_status"
grep -qx 'RESTORE_PUBLIC_PORTS=0' "$restore_status"
grep -qx 'RESTORE_RESIDUAL_RESOURCES=0' "$restore_status"

backup_stamp=$(sed -n 's/^BACKUP_TIMESTAMP=//p' "$backup_status")
restore_stamp=${latest_restore#brain-restore-}
backup_epoch=$(date -u -d "${backup_stamp:0:8} ${backup_stamp:9:2}:${backup_stamp:11:2}:${backup_stamp:13:2}" +%s)
restore_epoch=$(date -u -d "${restore_stamp:0:8} ${restore_stamp:9:2}:${restore_stamp:11:2}:${restore_stamp:13:2}" +%s)
backup_count=$(sed -n 's/^DATABASE_DUMP_COUNT=//p' "$backup_status")
restore_count=$(sed -n 's/^DATABASE_COUNT=//p' "$restore_status")
[[ "$backup_count" =~ ^[0-9]+$ && "$restore_count" =~ ^[0-9]+$ ]]

mkdir -p "$(dirname "$output")"
temporary=$(mktemp "${output}.XXXXXX")
trap 'rm -f "$temporary"' EXIT
{
    printf '# HELP codestra_backup_monitoring_up Recovery evidence exporter status.\n# TYPE codestra_backup_monitoring_up gauge\ncodestra_backup_monitoring_up 1\n'
    printf '# HELP codestra_backup_last_success_timestamp_seconds Latest encrypted backup completion.\n# TYPE codestra_backup_last_success_timestamp_seconds gauge\ncodestra_backup_last_success_timestamp_seconds %s\n' "$backup_epoch"
    printf '# HELP codestra_restore_test_last_success_timestamp_seconds Latest isolated restore certification.\n# TYPE codestra_restore_test_last_success_timestamp_seconds gauge\ncodestra_restore_test_last_success_timestamp_seconds %s\n' "$restore_epoch"
    printf '# HELP codestra_backup_database_count Databases in the latest encrypted backup.\n# TYPE codestra_backup_database_count gauge\ncodestra_backup_database_count %s\n' "$backup_count"
    printf '# HELP codestra_restore_database_count Databases in the latest isolated restore.\n# TYPE codestra_restore_database_count gauge\ncodestra_restore_database_count %s\n' "$restore_count"
} > "$temporary"
chmod 0644 "$temporary"
mv -f "$temporary" "$output"
trap - EXIT
