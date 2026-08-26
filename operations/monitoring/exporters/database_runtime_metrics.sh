#!/usr/bin/env bash
set -euo pipefail
umask 022
output=${CODESTRA_DATABASE_RUNTIME_METRICS_OUTPUT:-/var/lib/node_exporter/textfile_collector/codestra_database_runtime.prom}
temporary=$(mktemp "${output}.XXXXXX")
trap 'rm -f "$temporary"' EXIT

collect() {
  local service=$1 container=$2 user=$3 database=$4 values
  if ! values=$(docker exec "$container" psql -X -U "$user" -d "$database" -AtF '|' -v ON_ERROR_STOP=1 -c "select count(*),(select setting from pg_settings where name='max_connections'),(select count(*) from pg_locks where not granted),(select coalesce(sum(deadlocks),0) from pg_stat_database),pg_database_size(current_database()),pg_is_in_recovery()::int from pg_stat_activity"); then
    printf 'codestra_database_up{service="%s",container="%s"} 0\n' "$service" "$container" >> "$temporary"; return
  fi
  IFS='|' read -r connections maximum locks deadlocks size recovery <<< "$values"
  printf 'codestra_database_up{service="%s",container="%s"} 1\n' "$service" "$container" >> "$temporary"
  printf 'codestra_database_connections{service="%s"} %s\n' "$service" "$connections" >> "$temporary"
  printf 'codestra_database_max_connections{service="%s"} %s\n' "$service" "$maximum" >> "$temporary"
  printf 'codestra_database_waiting_locks{service="%s"} %s\n' "$service" "$locks" >> "$temporary"
  printf 'codestra_database_deadlocks_total{service="%s"} %s\n' "$service" "$deadlocks" >> "$temporary"
  printf 'codestra_database_size_bytes{service="%s"} %s\n' "$service" "$size" >> "$temporary"
  printf 'codestra_database_in_recovery{service="%s"} %s\n' "$service" "$recovery" >> "$temporary"
}

: > "$temporary"
collect shared-platform codestra-postgres-1 postgres postgres
collect kong codestra-kong-kong-db-1 kong kong
collect identity codestra-identity-identity-db-1 keycloak keycloak
collect websocket-primary codestra-websocket-gateway-postgres-1 codestra_realtime codestra_realtime
collect websocket-standby codestra-websocket-standby-031447a-postgres-1 codestra_realtime codestra_realtime
collect reseller-portal codestra-reseller-portal-postgres-1 reseller_portal reseller_portal
collect sms-api codestra-sms-api-postgres-1 codestra_sms codestra_sms

sender_count=$(docker exec codestra-websocket-gateway-postgres-1 psql -X -U codestra_realtime -d codestra_realtime -Atc "select count(*) from pg_stat_replication where state='streaming'")
receiver_count=$(docker exec codestra-websocket-standby-031447a-postgres-1 psql -X -U codestra_realtime -d codestra_realtime -Atc "select count(*) from pg_stat_wal_receiver where status='streaming'")
standby_recovery=$(docker exec codestra-websocket-standby-031447a-postgres-1 psql -X -U codestra_realtime -d codestra_realtime -Atc 'select pg_is_in_recovery()::int')
lag_bytes=$(docker exec codestra-websocket-gateway-postgres-1 psql -X -U codestra_realtime -d codestra_realtime -Atc "select coalesce(max(pg_wal_lsn_diff(pg_current_wal_lsn(),replay_lsn)),0)::bigint from pg_stat_replication")
printf 'codestra_websocket_db_replication_streaming %s\n' "$((sender_count > 0 && receiver_count > 0))" >> "$temporary"
printf 'codestra_websocket_db_wal_senders_streaming %s\n' "$sender_count" >> "$temporary"
printf 'codestra_websocket_db_wal_receivers_streaming %s\n' "$receiver_count" >> "$temporary"
printf 'codestra_websocket_db_standby_in_recovery %s\n' "$standby_recovery" >> "$temporary"
printf 'codestra_websocket_db_replication_lag_bytes %s\n' "$lag_bytes" >> "$temporary"
chmod 0644 "$temporary"
mv -f "$temporary" "$output"
trap - EXIT

