#!/usr/bin/env bash
set -euo pipefail
umask 022

backup_root=${CODESTRA_DATABASE_BACKUP_ROOT:-/opt/codestra/backups/database-certification}
restore_root=${CODESTRA_DATABASE_RESTORE_ROOT:-/opt/codestra/evidence/database-restore}
output=${CODESTRA_DATABASE_METRICS_OUTPUT:-/var/lib/node_exporter/textfile_collector/codestra_database_certification.prom}
latest_backup=$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' | sort | tail -1)
latest_restore=$(find "$restore_root" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' | sort | tail -1)
test -n "$latest_backup" -a -n "$latest_restore"
grep -qx DATABASE_BACKUP=PASS "$latest_backup/STATUS.txt"
grep -qx CHECKSUM=PASS "$latest_backup/STATUS.txt"
grep -qx ENCRYPTION=PASS "$latest_backup/STATUS.txt"
grep -qx DATABASE_RESTORE=PASS "$latest_restore/RESTORE-RESULT.txt"

to_epoch() {
  local stamp=$1
  date -u -d "${stamp:0:8} ${stamp:9:2}:${stamp:11:2}:${stamp:13:2}" +%s
}
backup_stamp=$(sed -n 's/^BACKUP_TIMESTAMP=//p' "$latest_backup/STATUS.txt")
restore_stamp=${latest_restore##*/}
offhost=$(grep -qx OFFHOST_COPY=PASS "$latest_backup/STATUS.txt" && echo 1 || echo 0)
temporary=$(mktemp "${output}.XXXXXX")
trap 'rm -f "$temporary"' EXIT
{
  printf 'codestra_database_backup_last_success_timestamp_seconds %s\n' "$(to_epoch "$backup_stamp")"
  printf 'codestra_database_restore_last_success_timestamp_seconds %s\n' "$(to_epoch "$restore_stamp")"
  printf 'codestra_database_backup_database_count 11\n'
  printf 'codestra_database_backup_checksum_ok 1\n'
  printf 'codestra_database_backup_encryption_ok 1\n'
  printf 'codestra_database_backup_offhost_ok %s\n' "$offhost"
} > "$temporary"
chmod 0644 "$temporary"
mv -f "$temporary" "$output"
trap - EXIT

