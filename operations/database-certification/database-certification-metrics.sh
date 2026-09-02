#!/usr/bin/env bash
set -euo pipefail
umask 022

backup_root=${CODESTRA_DATABASE_BACKUP_ROOT:-/opt/codestra/backups/database-certification}
restore_root=${CODESTRA_DATABASE_RESTORE_ROOT:-/opt/codestra/evidence/database-restore}
output=${CODESTRA_DATABASE_METRICS_OUTPUT:-/var/lib/node_exporter/textfile_collector/codestra_database_certification.prom}

select_latest_valid_backup() {
  local candidate
  while IFS= read -r candidate; do
    [[ -f "$candidate/STATUS.txt" && -f "$candidate/SHA256SUMS" && -f "$candidate/EVIDENCE-SHA256SUMS" ]] || continue
    grep -qx DATABASE_BACKUP=PASS "$candidate/STATUS.txt" || continue
    grep -qx CHECKSUM=PASS "$candidate/STATUS.txt" || continue
    grep -qx ENCRYPTION=PASS "$candidate/STATUS.txt" || continue
    (cd "$candidate" && sha256sum -c SHA256SUMS >/dev/null && sha256sum -c EVIDENCE-SHA256SUMS >/dev/null) || continue
    printf '%s\n' "$candidate"
    return 0
  done < <(find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' 2>/dev/null | sort -r)
  return 1
}

select_latest_valid_restore() {
  local candidate
  while IFS= read -r candidate; do
    [[ -f "$candidate/RESTORE-RESULT.txt" && -f "$candidate/SHA256SUMS" ]] || continue
    grep -qx DATABASE_RESTORE=PASS "$candidate/RESTORE-RESULT.txt" || continue
    (cd "$candidate" && sha256sum -c SHA256SUMS >/dev/null) || continue
    printf '%s\n' "$candidate"
    return 0
  done < <(find "$restore_root" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' 2>/dev/null | sort -r)
  return 1
}

status_value() {
  local key=$1 file=$2
  sed -n "s/^${key}=//p" "$file" | head -n 1
}

to_epoch() {
  local stamp=$1
  [[ "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]
  date -u -d "${stamp:0:8} ${stamp:9:2}:${stamp:11:2}:${stamp:13:2}" +%s
}

latest_backup=$(select_latest_valid_backup || true)
latest_restore=$(select_latest_valid_restore || true)

install -d -m 0755 "$(dirname "$output")"
temporary=$(mktemp "${output}.XXXXXX")
trap 'rm -f "$temporary"' EXIT

{
  if [[ -n "$latest_backup" ]]; then
    backup_status="$latest_backup/STATUS.txt"
    backup_stamp=$(status_value BACKUP_TIMESTAMP "$backup_status")
    database_count=$(status_value DATABASE_DUMP_COUNT "$backup_status")
    sqlite_count=$(status_value SQLITE_BACKUP_COUNT "$backup_status")
    standby_recovery=$(status_value WEBSOCKET_STANDBY_IN_RECOVERY "$backup_status")
    replication_streaming=$(status_value WEBSOCKET_REPLICATION_STREAMING "$backup_status")
    replication_lag=$(status_value WEBSOCKET_REPLICATION_LAG_BYTES "$backup_status")
    [[ "$database_count" =~ ^[0-9]+$ && "$sqlite_count" =~ ^[0-9]+$ ]]
    [[ "$standby_recovery" =~ ^[01]$ && "$replication_streaming" =~ ^[01]$ ]]
    [[ "$replication_lag" =~ ^[0-9]+$ ]]
    offhost=$(grep -qx OFFHOST_COPY=PASS "$backup_status" && echo 1 || echo 0)
    printf 'codestra_database_backup_last_success_timestamp_seconds %s\n' "$(to_epoch "$backup_stamp")"
    printf 'codestra_database_backup_database_count %s\n' "$((database_count + sqlite_count))"
    printf 'codestra_database_backup_checksum_ok 1\n'
    printf 'codestra_database_backup_encryption_ok 1\n'
    printf 'codestra_database_backup_offhost_ok %s\n' "$offhost"
    printf 'codestra_websocket_db_standby_in_recovery %s\n' "$standby_recovery"
    printf 'codestra_websocket_db_replication_streaming %s\n' "$replication_streaming"
    printf 'codestra_websocket_db_replication_lag_bytes %s\n' "$replication_lag"
  fi

  if [[ -n "$latest_restore" ]]; then
    restore_status="$latest_restore/RESTORE-RESULT.txt"
    restore_stamp=$(status_value RESTORE_TIMESTAMP "$restore_status")
    if [[ -z "$restore_stamp" ]]; then
      restore_stamp=${latest_restore##*/}
    fi
    printf 'codestra_database_restore_last_success_timestamp_seconds %s\n' "$(to_epoch "$restore_stamp")"
  fi
} > "$temporary"

chmod 0644 "$temporary"
mv -f "$temporary" "$output"
trap - EXIT
