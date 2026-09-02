#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=${CODESTRA_DATABASE_BACKUP_ROOT:-/opt/codestra/backups/database-certification}
gpg_home=${CODESTRA_DATABASE_BACKUP_GPG_HOME:-/etc/codestra/backup-gpg}
gpg_recipient=${CODESTRA_DATABASE_BACKUP_GPG_RECIPIENT:-Codestra Backup Recipient}
remote=${CODESTRA_DATABASE_BACKUP_REMOTE:-}
primary_container=${CODESTRA_WEBSOCKET_PRIMARY_CONTAINER:-codestra-websocket-gateway-postgres-1}
standby_container=${CODESTRA_WEBSOCKET_STANDBY_CONTAINER:-codestra-websocket-replica-postgres-1}
standby_max_lag_bytes=${CODESTRA_WEBSOCKET_STANDBY_MAX_LAG_BYTES:-16777216}
provisioning_container=${CODESTRA_PROVISIONING_CONTAINER:-codestra-provisioning-production-provisioning-service-1}
provisioning_volume=${CODESTRA_PROVISIONING_VOLUME:-codestra-provisioning-production_state}
retired_provisioning_volume=${CODESTRA_RETIRED_PROVISIONING_VOLUME:-codestra-provisioning-service_state}
minimum_free_percent=${CODESTRA_DATABASE_BACKUP_MINIMUM_FREE_PERCENT:-20}
retention_days=${CODESTRA_DATABASE_BACKUP_RETENTION_DAYS:-30}
stamp=$(date -u +%Y%m%dT%H%M%SZ)

install -d -m 0700 "$backup_root"
exec 9>"$backup_root/.backup.lock"
flock -n 9

[[ "$standby_max_lag_bytes" =~ ^[0-9]+$ ]]
[[ "$minimum_free_percent" =~ ^[0-9]+$ ]] && (( minimum_free_percent <= 50 ))
[[ "$retention_days" =~ ^[0-9]+$ ]] && (( retention_days >= 7 && retention_days <= 365 ))
available_percent=$(df -P "$backup_root" | awk 'NR==2 {gsub(/%/, "", $5); print 100-$5}')
(( available_percent >= minimum_free_percent ))

work=$(mktemp -d "${backup_root}/.work-${stamp}.XXXXXX")
archive="${work}.tar.gz"
final="${backup_root}/${stamp}"
backup_complete=false
pruned_backup_count=0
websocket_standby_in_recovery=0
websocket_replication_streaming=0
websocket_replication_lag_bytes=

cleanup() {
  find "$work" -xdev -type f -delete 2>/dev/null || true
  find "$work" -xdev -depth -type d -empty -delete 2>/dev/null || true
  rm -f -- "$archive"
  if [[ "$backup_complete" != true && -d "$final" ]]; then
    find "$final" -xdev -depth -delete 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'printf "DATABASE_BACKUP=FAIL\n" >&2' ERR

install -d -m 0700 "$final"
command -v docker >/dev/null
command -v gpg >/dev/null
command -v sha256sum >/dev/null

postgres_client_image=${CODESTRA_POSTGRES_CLIENT_IMAGE:-postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94}

db_client() {
  local container=$1 user=$2 database=$3
  shift 3
  local password password_file password_source
  password=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container" |
    sed -n 's/^POSTGRES_PASSWORD=//p' | head -n 1)
  if [[ -n "$password" ]]; then
    docker run --rm --network "container:$container" -e PGPASSWORD="$password" \
      "$postgres_client_image" "$@" -h 127.0.0.1 -U "$user" -d "$database"
    return
  fi
  password_file=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container" |
    sed -n 's/^POSTGRES_PASSWORD_FILE=//p' | head -n 1)
  test -n "$password_file"
  password_source=$(docker inspect --format '{{range .Mounts}}{{.Source}}|{{.Destination}}{{println}}{{end}}' "$container" |
    awk -F'|' -v destination="$password_file" '$2 == destination {print $1; exit}')
  test -n "$password_source"
  docker run --rm --network "container:$container" \
    -v "$password_source:/run/codestra-db-password:ro" \
    "$postgres_client_image" sh -c \
    'export PGPASSWORD="$(cat /run/codestra-db-password)"; command=$1; shift; exec "$command" "$@"' \
    sh "$@" -h 127.0.0.1 -U "$user" -d "$database"
}

dump() {
  local container=$1 user=$2 database=$3 output=$4
  printf 'DATABASE_BACKUP_STEP=dump:%s\n' "$output"
  test "$(docker inspect -f '{{.State.Status}}' "$container")" = running
  db_client "$container" "$user" "$database" pg_isready >/dev/null
  db_client "$container" "$user" "$database" pg_dump -Fc > "$work/$output.dump"
  test -s "$work/$output.dump"
  db_client "$container" "$user" "$database" psql -X -At -v ON_ERROR_STOP=1 \
    -c "select current_setting('server_version'),pg_is_in_recovery(),count(*) from information_schema.tables where table_schema='public'" \
    > "$work/$output.catalog"
}

dump_local_peer() {
  local container=$1 user=$2 database=$3 output=$4
  printf 'DATABASE_BACKUP_STEP=dump:%s\n' "$output"
  test "$(docker inspect -f '{{.State.Status}}' "$container")" = running
  docker exec -u postgres "$container" pg_isready -U "$user" -d "$database" >/dev/null
  docker exec -u postgres "$container" pg_dump -U "$user" -d "$database" -Fc > "$work/$output.dump"
  test -s "$work/$output.dump"
  docker exec -u postgres "$container" psql -X -At -v ON_ERROR_STOP=1 \
    -U "$user" -d "$database" \
    -c "select current_setting('server_version'),pg_is_in_recovery(),count(*) from information_schema.tables where table_schema='public'" \
    > "$work/$output.catalog"
}

verify_streaming_standby() {
  local primary=$1 standby=$2 user=$3 database=$4
  local standby_state recovery receiving replay_lsn
  local primary_state primary_recovery primary_lsn lag

  test "$(docker inspect -f '{{.State.Status}}' "$primary")" = running
  test "$(docker inspect -f '{{.State.Status}}' "$standby")" = running

  standby_state=$(docker exec -u postgres "$standby" psql -X -At -v ON_ERROR_STOP=1 \
    -U "$user" -d "$database" \
    -c "select pg_is_in_recovery(), exists(select 1 from pg_stat_wal_receiver where status='streaming'), coalesce(pg_last_wal_replay_lsn()::text,'')")
  IFS='|' read -r recovery receiving replay_lsn <<<"$standby_state"
  [[ "$recovery" == t && "$receiving" == t ]]
  [[ "$replay_lsn" =~ ^[0-9A-F]+/[0-9A-F]+$ ]]

  primary_state=$(db_client "$primary" "$user" "$database" psql -X -At -v ON_ERROR_STOP=1 \
    -c "select pg_is_in_recovery(), pg_current_wal_flush_lsn()::text")
  IFS='|' read -r primary_recovery primary_lsn <<<"$primary_state"
  [[ "$primary_recovery" == f ]]
  [[ "$primary_lsn" =~ ^[0-9A-F]+/[0-9A-F]+$ ]]

  lag=$(db_client "$primary" "$user" "$database" psql -X -At -v ON_ERROR_STOP=1 \
    -c "select greatest(pg_wal_lsn_diff('${primary_lsn}'::pg_lsn,'${replay_lsn}'::pg_lsn)::bigint,0)")
  [[ "$lag" =~ ^[0-9]+$ ]]
  (( lag <= standby_max_lag_bytes ))

  websocket_standby_in_recovery=1
  websocket_replication_streaming=1
  websocket_replication_lag_bytes=$lag
}

prune_completed_backups() {
  local now cutoff candidate name candidate_epoch
  now=$(date -u +%s)
  cutoff=$((now - retention_days * 86400))
  while IFS= read -r -d '' candidate; do
    [[ "$candidate" != "$final" ]] || continue
    [[ -f "$candidate/STATUS.txt" && -f "$candidate/SHA256SUMS" && -f "$candidate/EVIDENCE-SHA256SUMS" ]] || continue
    grep -qx DATABASE_BACKUP=PASS "$candidate/STATUS.txt" || continue
    grep -qx CHECKSUM=PASS "$candidate/STATUS.txt" || continue
    grep -qx ENCRYPTION=PASS "$candidate/STATUS.txt" || continue
    (cd "$candidate" && sha256sum -c SHA256SUMS >/dev/null && sha256sum -c EVIDENCE-SHA256SUMS >/dev/null) || continue
    name=${candidate##*/}
    candidate_epoch=$(date -u -d "${name:0:8} ${name:9:2}:${name:11:2}:${name:13:2}" +%s 2>/dev/null) || continue
    (( candidate_epoch < cutoff )) || continue
    find "$candidate" -xdev -depth -delete
    ((pruned_backup_count += 1))
  done < <(find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' -print0)
}

dump codestra-postgres-1 postgres codestra_odoo shared-odoo
dump codestra-postgres-1 postgres codestra_middleware shared-middleware
dump codestra-postgres-1 postgres codestra_n8n shared-n8n
dump codestra-postgres-1 postgres control_plane shared-control-plane
dump codestra-kong-kong-db-1 kong kong kong
dump codestra-identity-identity-db-1 keycloak keycloak identity
dump "$primary_container" codestra_realtime codestra_realtime websocket-primary
verify_streaming_standby "$primary_container" "$standby_container" codestra_realtime codestra_realtime
dump_local_peer "$standby_container" codestra_realtime codestra_realtime websocket-standby-independent
dump codestra-reseller-portal-postgres-1 reseller_portal reseller_portal reseller-portal
dump codestra-sms-api-postgres-1 codestra_sms codestra_sms sms-api

printf 'DATABASE_BACKUP_STEP=provisioning-sqlite\n'
provisioning_state_path=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$provisioning_container" |
  sed -n 's/^STATE_DATABASE_PATH=//p' | head -n 1)
test "$provisioning_state_path" = /var/lib/codestra/provisioning.db
docker volume inspect "$provisioning_volume" >/dev/null
current_mount=$(docker inspect --format '{{range .Mounts}}{{.Name}}|{{.Destination}}{{println}}{{end}}' "$provisioning_container" |
  awk -F'|' '$2=="/var/lib/codestra" {print $1; exit}')
test "$current_mount" = "$provisioning_volume"
# A retained legacy volume is a rollback artifact only; it must never become
# the selected source merely because it exists.
test "$provisioning_volume" != "$retired_provisioning_volume"
docker run --rm -i \
  -e STATE_DATABASE_PATH="$provisioning_state_path" \
  -v "$provisioning_volume:/var/lib/codestra:ro" \
  -v "$work:/backup" \
  python@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df \
  python - <<'PY'
import os, sqlite3
source = sqlite3.connect(f"file:{os.environ['STATE_DATABASE_PATH']}?mode=ro", uri=True)
target = sqlite3.connect('/backup/provisioning.sqlite3')
source.backup(target)
assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
target.close(); source.close()
PY
test -s "$work/provisioning.sqlite3"

(
  printf 'DATABASE_BACKUP_STEP=archive\n'
  cd "$work"
  sha256sum ./* > PLAINTEXT-SHA256SUMS
  sha256sum -c PLAINTEXT-SHA256SUMS
  tar -czf "$archive" .
)
printf 'DATABASE_BACKUP_STEP=encrypt\n'
gpg --homedir "$gpg_home" --no-random-seed-file --batch --yes --trust-model always \
  --recipient "$gpg_recipient" --encrypt \
  --output "$final/databases-${stamp}.tar.gz.gpg" "$archive"
(
  cd "$final"
  sha256sum "databases-${stamp}.tar.gz.gpg" > SHA256SUMS
  sha256sum -c SHA256SUMS
)

offhost=PENDING
if [[ -n "$remote" ]]; then
  printf 'DATABASE_BACKUP_STEP=offhost-copy\n'
  remote_host=${remote%%:*}
  remote_root=${remote#*:}
  test "$remote_host" != "$remote" -a -n "$remote_root"
  ssh -o BatchMode=yes "$remote_host" "install -d -m 0700 '$remote_root/$stamp'"
  scp -q -o BatchMode=yes -o IdentitiesOnly=yes \
    "$final/databases-${stamp}.tar.gz.gpg" "$final/SHA256SUMS" "$remote_host:$remote_root/$stamp/"
  ssh -o BatchMode=yes "$remote_host" \
    "cd '$remote_root/$stamp' && sha256sum -c SHA256SUMS >/dev/null && sha256sum 'databases-${stamp}.tar.gz.gpg'" \
    > "$final/REMOTE-SHA256SUMS"
  diff -u <(awk '{print $1}' "$final/SHA256SUMS") <(awk '{print $1}' "$final/REMOTE-SHA256SUMS")
  offhost=PASS
fi

prune_completed_backups
cat > "$final/STATUS.txt" <<EOF
DATABASE_BACKUP=PASS
BACKUP_TIMESTAMP=${stamp}
DATABASE_DUMP_COUNT=10
SQLITE_BACKUP_COUNT=1
CHECKSUM=PASS
ENCRYPTION=PASS
OFFHOST_COPY=${offhost}
WEBSOCKET_STANDBY_IN_RECOVERY=${websocket_standby_in_recovery}
WEBSOCKET_REPLICATION_STREAMING=${websocket_replication_streaming}
WEBSOCKET_REPLICATION_LAG_BYTES=${websocket_replication_lag_bytes}
LOCAL_RETENTION_DAYS=${retention_days}
LOCAL_RETENTION_PRUNED=${pruned_backup_count}
EOF
sha256sum "$final/STATUS.txt" > "$final/EVIDENCE-SHA256SUMS"
backup_complete=true
printf '%s\n' "$final"
