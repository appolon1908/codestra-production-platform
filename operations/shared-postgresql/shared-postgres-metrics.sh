#!/usr/bin/env bash
set -euo pipefail
umask 077

authority=/etc/codestra/secrets/shared-postgresql
container="$(<"$authority/postgres-container")"
output=/var/lib/node_exporter/textfile_collector/codestra_shared_postgres.prom
temporary="$(mktemp "${output}.XXXXXX")"
trap 'find "$temporary" -delete 2>/dev/null || true' EXIT

read -r archived failed last_epoch < <(docker exec "$container" psql -U postgres -d postgres -XAt -F ' ' -c \
  "select archived_count,failed_count,coalesce(extract(epoch from last_archived_time)::bigint,0) from pg_stat_archiver")
disk_used="$(df -P /var/lib/docker | awk 'NR==2 {gsub(/%/,\"\",$5); print $5}')"
base_last=/opt/codestra/backups/postgresql-shared/base/LAST_SUCCESS
pitr_last=/var/lib/codestra-shared-postgresql/LAST_PITR_SUCCESS
base_epoch=0
pitr_epoch=0
[[ -f "$base_last" ]] && base_epoch="$(stat -c %Y "$base_last")"
[[ -f "$pitr_last" ]] && pitr_epoch="$(stat -c %Y "$pitr_last")"
cat >"$temporary" <<EOF
codestra_shared_postgres_wal_archived_total $archived
codestra_shared_postgres_wal_archive_failures_total $failed
codestra_shared_postgres_wal_last_success_timestamp_seconds $last_epoch
codestra_shared_postgres_base_backup_last_success_timestamp_seconds $base_epoch
codestra_shared_postgres_pitr_last_success_timestamp_seconds $pitr_epoch
codestra_shared_postgres_disk_used_percent $disk_used
EOF
chmod 0644 "$temporary"
mv "$temporary" "$output"
