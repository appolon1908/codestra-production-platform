#!/usr/bin/env bash
set -euo pipefail
umask 077

authority="${CODESTRA_SHARED_POSTGRES_AUTHORITY:-/etc/codestra/secrets/shared-postgresql}"
state="${CODESTRA_SHARED_POSTGRES_STATE:-/var/lib/codestra-shared-postgresql}"
container="$(<"$authority/postgres-container")"
output="${CODESTRA_SHARED_POSTGRES_METRICS_OUTPUT:-/var/lib/node_exporter/textfile_collector/codestra_shared_postgres.prom}"
temporary="$(mktemp "${output}.XXXXXX")"
trap 'find "$temporary" -delete 2>/dev/null || true' EXIT

postgres_up=1
archived=0
failed=0
last_epoch=0
if values="$(docker exec "$container" psql -U postgres -d postgres -XAt -F ' ' -c \
  "select archived_count,failed_count,coalesce(extract(epoch from last_archived_time)::bigint,0) from pg_stat_archiver" 2>/dev/null)"; then
  read -r archived failed last_epoch <<<"$values"
else
  postgres_up=0
fi
for value in "$postgres_up" "$archived" "$failed" "$last_epoch"; do
  [[ "$value" =~ ^[0-9]+$ ]]
done

disk_used="$(df -P /var/lib/docker | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
[[ "$disk_used" =~ ^[0-9]+$ ]]
base_last=/opt/codestra/backups/postgresql-shared/base/LAST_SUCCESS
pitr_last="$state/LAST_PITR_SUCCESS"
base_epoch=0
pitr_epoch=0
cleanup_deleted=0
cleanup_failed=0
spool_bytes=0
spool_critical=0
offhost_epoch=0
restic_last=0
restic_failures=0
restic_used=0
restic_capacity=0
[[ -f "$base_last" ]] && base_epoch="$(stat -c %Y "$base_last")"
[[ -f "$pitr_last" ]] && pitr_epoch="$(stat -c %Y "$pitr_last")"
[[ -f "$state/wal_cleanup_deleted_total" ]] && cleanup_deleted="$(<"$state/wal_cleanup_deleted_total")"
[[ -f "$state/wal_cleanup_failures_total" ]] && cleanup_failed="$(<"$state/wal_cleanup_failures_total")"
[[ -f "$state/wal_spool_disk_critical" ]] && spool_critical="$(<"$state/wal_spool_disk_critical")"
[[ -d /var/spool/codestra/postgresql-shared/wal ]] && spool_bytes="$(du -sb /var/spool/codestra/postgresql-shared/wal | awk '{print $1}')"
[[ -f /opt/codestra/backups/postgresql-shared/wal/LAST_OFFHOST_SUCCESS ]] && offhost_epoch="$(stat -c %Y /opt/codestra/backups/postgresql-shared/wal/LAST_OFFHOST_SUCCESS)"
[[ -f "$state/restic_maintenance_last_success" ]] && restic_last="$(<"$state/restic_maintenance_last_success")"
[[ -f "$state/restic_maintenance_failures_total" ]] && restic_failures="$(<"$state/restic_maintenance_failures_total")"
[[ -f "$state/restic_repository_used_bytes" ]] && restic_used="$(<"$state/restic_repository_used_bytes")"
[[ -f "$state/restic_repository_capacity_bytes" ]] && restic_capacity="$(<"$state/restic_repository_capacity_bytes")"
for value in "$base_epoch" "$pitr_epoch" "$cleanup_deleted" "$cleanup_failed" "$spool_bytes" \
  "$spool_critical" "$offhost_epoch" "$restic_last" "$restic_failures" "$restic_used" "$restic_capacity"; do
  [[ "$value" =~ ^[0-9]+$ ]]
done

cat >"$temporary" <<EOF
codestra_shared_postgres_up $postgres_up
codestra_shared_postgres_wal_archived_total $archived
codestra_shared_postgres_wal_archive_failures_total $failed
codestra_shared_postgres_wal_last_success_timestamp_seconds $last_epoch
codestra_shared_postgres_base_backup_last_success_timestamp_seconds $base_epoch
codestra_shared_postgres_pitr_last_success_timestamp_seconds $pitr_epoch
codestra_shared_postgres_disk_used_percent $disk_used
codestra_shared_postgres_wal_spool_bytes $spool_bytes
codestra_shared_postgres_wal_spool_disk_critical $spool_critical
codestra_shared_postgres_wal_offhost_last_success_timestamp_seconds $offhost_epoch
codestra_shared_postgres_wal_cleanup_deleted_total $cleanup_deleted
codestra_shared_postgres_wal_cleanup_failures_total $cleanup_failed
codestra_shared_postgres_restic_maintenance_last_success_timestamp_seconds $restic_last
codestra_shared_postgres_restic_maintenance_failures_total $restic_failures
codestra_shared_postgres_restic_repository_used_bytes $restic_used
codestra_shared_postgres_restic_repository_capacity_bytes $restic_capacity
EOF
chmod 0644 "$temporary"
mv "$temporary" "$output"
trap - EXIT
