#!/usr/bin/env bash
set -euo pipefail
umask 022

collector=/var/lib/node_exporter/textfile_collector
output="$collector/kong_database.prom"
temporary="$(mktemp "$collector/.kong_database.prom.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
db=codestra-kong-kong-db-1
backup_root=/opt/codestra/backups/kong-database

stamp_to_epoch() {
  local stamp="${1%%-*}"
  if [[ "$stamp" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
    date -u -d "${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]} UTC" +%s
    return
  fi
  [[ "$stamp" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})Z$ ]] || return 1
  date -u -d "${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]} UTC" +%s
}

values="$(docker exec "$db" psql -U kong -d kong -XAt -F '|' -v ON_ERROR_STOP=1 -c "
select count(*) filter (where state is not null), current_setting('max_connections')::int,
count(*) filter (where state='idle in transaction'),
(select count(*) from pg_locks where not granted),
(select deadlocks from pg_stat_database where datname=current_database()),
pg_database_size(current_database()),
coalesce(max(extract(epoch from clock_timestamp()-query_start)) filter
  (where state='active' and pid<>pg_backend_pid()),0),
(select write_time from pg_stat_checkpointer),
pg_wal_lsn_diff(pg_current_wal_lsn(),'0/0') from pg_stat_activity;
")"
IFS='|' read -r connections max_connections idle_transaction lock_waits deadlocks db_size longest_query checkpoint_write wal_bytes <<<"$values"
disk_used_percent="$(df -P /var/lib/docker | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
now="$(date +%s)"
backup_timestamp=0
if [[ -s "$backup_root/LAST_SUCCESS" ]]; then
  backup_timestamp="$(stamp_to_epoch "$(cat "$backup_root/LAST_SUCCESS")")"
fi
backup_age=$(( backup_timestamp > 0 ? now - backup_timestamp : 2147483647 ))
restore_timestamp=0
if [[ -s /var/lib/codestra-kong-database/LAST_RESTORE_SUCCESS ]]; then
  restore_timestamp="$(stamp_to_epoch "$(cat /var/lib/codestra-kong-database/LAST_RESTORE_SUCCESS)")"
fi
migration_up_to_date=0
if docker exec codestra-kong-kong-gateway-1 kong migrations list >/dev/null 2>&1; then
  migration_up_to_date=1
fi
cat >"$temporary" <<EOF
# HELP codestra_kong_db_up Direct PostgreSQL readback succeeded.
# TYPE codestra_kong_db_up gauge
codestra_kong_db_up 1
# HELP codestra_kong_db_connections Current PostgreSQL connections.
# TYPE codestra_kong_db_connections gauge
codestra_kong_db_connections $connections
# HELP codestra_kong_db_max_connections Configured PostgreSQL connection limit.
# TYPE codestra_kong_db_max_connections gauge
codestra_kong_db_max_connections $max_connections
# HELP codestra_kong_db_idle_in_transaction Idle-in-transaction sessions.
# TYPE codestra_kong_db_idle_in_transaction gauge
codestra_kong_db_idle_in_transaction $idle_transaction
# HELP codestra_kong_db_lock_waits Unacquired PostgreSQL locks.
# TYPE codestra_kong_db_lock_waits gauge
codestra_kong_db_lock_waits $lock_waits
# HELP codestra_kong_db_deadlocks_total Database deadlocks.
# TYPE codestra_kong_db_deadlocks_total counter
codestra_kong_db_deadlocks_total $deadlocks
# HELP codestra_kong_db_size_bytes Kong database size.
# TYPE codestra_kong_db_size_bytes gauge
codestra_kong_db_size_bytes $db_size
# HELP codestra_kong_db_longest_active_query_seconds Longest active query age.
# TYPE codestra_kong_db_longest_active_query_seconds gauge
codestra_kong_db_longest_active_query_seconds $longest_query
# HELP codestra_kong_db_checkpoint_write_milliseconds Cumulative checkpoint write time.
# TYPE codestra_kong_db_checkpoint_write_milliseconds counter
codestra_kong_db_checkpoint_write_milliseconds $checkpoint_write
# HELP codestra_kong_db_wal_bytes Current WAL position expressed as bytes.
# TYPE codestra_kong_db_wal_bytes gauge
codestra_kong_db_wal_bytes $wal_bytes
# HELP codestra_kong_db_disk_used_percent Host filesystem utilization.
# TYPE codestra_kong_db_disk_used_percent gauge
codestra_kong_db_disk_used_percent $disk_used_percent
# HELP codestra_kong_db_backup_age_seconds Age of latest successful off-host backup.
# TYPE codestra_kong_db_backup_age_seconds gauge
codestra_kong_db_backup_age_seconds $backup_age
# HELP codestra_kong_db_backup_last_success_timestamp_seconds Latest backup timestamp.
# TYPE codestra_kong_db_backup_last_success_timestamp_seconds gauge
codestra_kong_db_backup_last_success_timestamp_seconds $backup_timestamp
# HELP codestra_kong_db_restore_last_success_timestamp_seconds Latest restore rehearsal timestamp.
# TYPE codestra_kong_db_restore_last_success_timestamp_seconds gauge
codestra_kong_db_restore_last_success_timestamp_seconds $restore_timestamp
# HELP codestra_kong_db_migration_up_to_date Kong migration command succeeds.
# TYPE codestra_kong_db_migration_up_to_date gauge
codestra_kong_db_migration_up_to_date $migration_up_to_date
# HELP codestra_kong_db_replication_expected Whether HA replication is approved and expected.
# TYPE codestra_kong_db_replication_expected gauge
codestra_kong_db_replication_expected 0
# HELP codestra_kong_db_replication_lag_seconds Replica replay lag, or -1 when no replica exists.
# TYPE codestra_kong_db_replication_lag_seconds gauge
codestra_kong_db_replication_lag_seconds -1
EOF
chmod 0644 "$temporary"
mv -f "$temporary" "$output"
