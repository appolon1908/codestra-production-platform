#!/usr/bin/env bash
set -euo pipefail
umask 077

image="${POSTGRES_17_IMAGE:-postgres:17.6}"
stamp="$(date -u +%Y%m%d%H%M%S)-$$"
network="shared-pitr-test-$stamp"
primary="shared-pitr-primary-$stamp"
recovery="shared-pitr-recovery-$stamp"
work="$(mktemp -d /var/tmp/shared-pitr-integration.XXXXXX)"
package="$(cd "$(dirname "$0")/../../operations/shared-postgresql" && pwd)"

cleanup() {
  docker rm -f "$primary" "$recovery" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  gpgconf --homedir "$work/authority/gpg" --kill gpg-agent >/dev/null 2>&1 || true
  if [[ "${SHARED_PITR_KEEP_WORK:-0}" == 1 ]]; then
    printf 'SYNTHETIC_WORKDIR=%s\n' "$work" >&2
    return
  fi
  find "$work" -xdev -type f -delete 2>/dev/null || true
  find "$work" -depth -type d -empty -delete 2>/dev/null || true
}
trap cleanup EXIT
trap 'printf "INTEGRATION_FAILURE_LINE=%s COMMAND=%s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

for command in docker gpg restic jq; do command -v "$command" >/dev/null; done
mkdir -p "$work"/{stage,spool,state,restic,restic-cache,authority/gpg,recovery-secrets,base-root,recovery,recovered-archive,relocated}
postgres_uid="$(docker run --rm --network none --entrypoint id "$image" -u postgres)"
postgres_gid="$(docker run --rm --network none --entrypoint id "$image" -g postgres)"
chown root:"$postgres_gid" "$work/stage"
chmod 0770 "$work/stage"
test "$(stat -c '%u:%g:%a' "$work/stage")" = "0:${postgres_gid}:770"

gpg --homedir "$work/authority/gpg" --batch --passphrase '' --quick-generate-key \
  'Shared PITR Synthetic <shared-pitr-synthetic@invalid>' rsa2048 encr 1d >/dev/null 2>&1
printf '%s\n' 'shared-pitr-synthetic@invalid' >"$work/authority/archive-recipient"
printf '%s\n' 'synthetic-restic-password' >"$work/authority/restic-password"
printf '%s\n' "$work/restic" >"$work/authority/restic-repository"
printf '%s\n' '7' >"$work/authority/wal-retention-days"
printf '%s\n' 'CHG-SYNTHETIC-PITR' >"$work/authority/current-change-id"
find "$work/authority" -maxdepth 1 -type f -exec chmod 0600 {} +
RESTIC_PASSWORD_FILE="$work/authority/restic-password" restic -r "$work/restic" init >/dev/null

if [[ -n "${SHARED_PITR_TEST_SUBNET:-}" ]]; then
  docker network create --internal --subnet "$SHARED_PITR_TEST_SUBNET" "$network" >/dev/null
else
  for third_octet in $(seq 200 254); do
    if docker network create --internal --subnet "10.253.${third_octet}.0/28" "$network" >/dev/null 2>&1; then
      break
    fi
  done
  docker network inspect "$network" >/dev/null
fi
test_subnet="$(docker network inspect "$network" --format '{{(index .IPAM.Config 0).Subnet}}')"
docker run -d --name "$primary" --network "$network" --network-alias primary \
  --mount "type=bind,src=$work/stage,dst=/archive" \
  --mount "type=bind,src=$package/codestra-shared-postgres-stage-wal.sh,dst=/usr/local/bin/stage-wal.sh,readonly" \
  -e POSTGRES_PASSWORD=synthetic-rehearsal-only -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
  -e CODESTRA_SHARED_WAL_STAGE=/archive "$image" -c wal_level=replica -c archive_mode=on \
  -c "archive_command=/usr/local/bin/stage-wal.sh %p %f" -c archive_timeout=1s >/dev/null
for _ in $(seq 1 60); do docker exec "$primary" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
docker exec "$primary" pg_isready -U postgres >/dev/null
inspect="$(docker inspect "$primary")"
if grep -Eqi 'restic-password|object-secret|authority/gpg|archive-recipient' <<<"$inspect"; then exit 1; fi
test "$(docker exec -u postgres "$primary" id -u)" = "$postgres_uid"

docker exec -u postgres "$primary" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "create role pitr_backup login replication password 'synthetic-backup-only'; create table pitr_marker(name text primary key, created_at timestamptz default clock_timestamp());" >/dev/null
docker exec "$primary" sh -ec \
  "printf '%s\n' 'host replication pitr_backup $test_subnet scram-sha-256' >>\"\$PGDATA/pg_hba.conf\""
docker exec -u postgres "$primary" pg_ctl reload >/dev/null
resolved_image="$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')"
printf '%s\n' "$resolved_image" >"$work/authority/postgres-image"
printf '%s\n' "$network" >"$work/authority/postgres-network"
printf '%s\n' 'primary' >"$work/authority/postgres-host"
printf '%s\n' '5432' >"$work/authority/postgres-port"
printf '%s\n' 'pitr_backup' >"$work/authority/backup-role"
printf '%s\n' 'primary:5432:*:pitr_backup:synthetic-backup-only' >"$work/authority/backup-passfile"
find "$work/authority" -maxdepth 1 -type f -exec chmod 0600 {} +

CODESTRA_SHARED_POSTGRES_AUTHORITY="$work/authority" CODESTRA_SHARED_POSTGRES_BASE_ROOT="$work/base-root" \
CODESTRA_SHARED_RESTIC_CACHE="$work/restic-cache" "$package/create-base-backup.sh"
base_destination="$(find "$work/base-root" -mindepth 1 -maxdepth 1 -type d ! -name .restic-cache | head -1)"
test -n "$base_destination"
(cd "$base_destination" && sha256sum -c SHA256SUMS >/dev/null)
cp -a "$base_destination/." "$work/relocated/"
(cd "$work/relocated" && sha256sum -c SHA256SUMS >/dev/null)
gpg --homedir "$work/authority/gpg" --batch --quiet --decrypt --output "$work/relocated/base-bundle.tar" "$work/relocated/base.tar.gpg"
tar -xf "$work/relocated/base-bundle.tar" -C "$work/relocated"
tar -xf "$work/relocated/base.tar" -C "$work/recovery"
find "$work/recovery/pg_wal" -maxdepth 1 -type f -name '[0-9A-F]*' | grep -q .
cp "$work/relocated/backup_manifest" "$work/recovery/backup_manifest"

docker exec -u postgres "$primary" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "insert into pitr_marker(name) values ('pre-target')" >/dev/null
docker exec -u postgres "$primary" psql -U postgres -d postgres -Atqc 'select pg_switch_wal()' >/dev/null
for _ in $(seq 1 30); do find "$work/stage" -maxdepth 1 -type f -name '[0-9A-F]*' | grep -q . && break; sleep 1; done

offload() {
  CODESTRA_SHARED_POSTGRES_AUTHORITY="$work/authority" CODESTRA_SHARED_WAL_STAGE="$work/stage" \
  CODESTRA_SHARED_WAL_ARCHIVE="$work/spool" CODESTRA_SHARED_POSTGRES_STATE="$work/state" \
  CODESTRA_SHARED_RESTIC_CACHE="$work/restic-cache" CODESTRA_SHARED_POSTGRES_PRUNE_HELPER="$package/codestra-shared-postgres-prune-wal.sh" \
    "$package/codestra-shared-postgres-archive-wal.sh"
}
offload
find "$work/stage" -maxdepth 1 -type f -name '*.offhost' | grep -q .
! find "$work/spool" -maxdepth 1 -type f -name '*.gpg.sha256' | grep -q .
RESTIC_PASSWORD_FILE="$work/authority/restic-password" restic -r "$work/restic" snapshots --json --tag shared-postgresql-wal | jq -e 'length > 0' >/dev/null

target='codestra_synthetic_pre_target'
docker exec -u postgres "$primary" psql -U postgres -d postgres -Atqc "select pg_create_restore_point('$target')" >/dev/null
sleep 2
docker exec -u postgres "$primary" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "insert into pitr_marker(name) values ('post-target')" >/dev/null
staged_before="$(find "$work/stage" -maxdepth 1 -type f -regextype posix-extended -regex '.*/[0-9A-F]{24}' | wc -l)"
docker exec -u postgres "$primary" psql -U postgres -d postgres -Atqc 'select pg_switch_wal()' >/dev/null
for _ in $(seq 1 30); do
  staged_after="$(find "$work/stage" -maxdepth 1 -type f -regextype posix-extended -regex '.*/[0-9A-F]{24}' | wc -l)"
  (( staged_after > staged_before )) && break
  sleep 1
done
(( staged_after > staged_before ))
offload

first_wal="$(find "$work/stage" -maxdepth 1 -type f -regextype posix-extended -regex '.*/[0-9A-F]{24}' | head -1)"
first_name="${first_wal##*/}"
while IFS= read -r -d '' marker; do
  snapshot_id="$(awk -F= '$1=="REMOTE_SNAPSHOT_ID"{print $2}' "$marker")"
  artifact_path="$(awk -F= '$1=="ARTIFACT_PATH"{print substr($0,index($0,"=")+1)}' "$marker")"
  artifact_name="${artifact_path##*/}"
  RESTIC_PASSWORD_FILE="$work/authority/restic-password" restic -r "$work/restic" dump "$snapshot_id" "$artifact_path" >"$work/recovered-archive/$artifact_name"
  RESTIC_PASSWORD_FILE="$work/authority/restic-password" restic -r "$work/restic" dump "$snapshot_id" "$artifact_path.sha256" >"$work/recovered-archive/$artifact_name.sha256"
done < <(find "$work/stage" -maxdepth 1 -type f -name '*.offhost' -print0)
chown -R "$postgres_uid:$postgres_gid" "$work/recovered-archive"
chmod 0700 "$work/recovered-archive"
cp -a "$work/authority/gpg" "$work/recovery-secrets/gpg"
chown -R "$postgres_uid:$postgres_gid" "$work/recovery-secrets"
chmod 0700 "$work/recovery-secrets" "$work/recovery-secrets/gpg"
CODESTRA_SHARED_RECOVERY_ARCHIVE="$work/recovered-archive" CODESTRA_SHARED_RECOVERY_SECRETS="$work/authority" \
  "$package/codestra-shared-postgres-restore-wal.sh" "$first_name" "$work/relocated/restored-wal"
cmp "$first_wal" "$work/relocated/restored-wal"

failed_source="$work/stage/00000001000000000000FFFE"
cp "$first_wal" "$failed_source"
printf '%s\n' "$work/not-a-restic-repository" >"$work/authority/restic-repository"
if offload >/dev/null 2>&1; then exit 1; fi
test -s "$failed_source" -a ! -e "$failed_source.offhost"
printf '%s\n' "$work/restic" >"$work/authority/restic-repository"

docker stop "$primary" >/dev/null
printf "restore_command = '/usr/local/bin/restore-wal.sh %%f %%p'\nrecovery_target_name = '%s'\nrecovery_target_action = 'promote'\n" "$target" >>"$work/recovery/postgresql.auto.conf"
touch "$work/recovery/recovery.signal"
chown -R "$postgres_uid:$postgres_gid" "$work/recovery"
chmod 0700 "$work/recovery"
docker run -d --name "$recovery" --network "$network" \
  --mount "type=bind,src=$work/recovery,dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=$work/recovered-archive,dst=/recovery-archive,readonly" \
  --mount "type=bind,src=$work/recovery-secrets,dst=/run/recovery-secrets,readonly" \
  --mount "type=bind,src=$package/codestra-shared-postgres-restore-wal.sh,dst=/usr/local/bin/restore-wal.sh,readonly" "$image" >/dev/null
for _ in $(seq 1 90); do
  docker exec "$recovery" pg_isready -U postgres >/dev/null 2>&1 && break
  [[ "$(docker inspect "$recovery" --format '{{.State.Running}}')" == true ]] || {
    docker logs "$recovery" >&2
    exit 1
  }
  sleep 1
done
if ! docker exec "$recovery" pg_isready -U postgres >/dev/null; then
  docker logs "$recovery" >&2
  exit 1
fi
for _ in $(seq 1 90); do
  recovery_state="$(docker exec -u postgres "$recovery" psql -U postgres -d postgres -Atqc 'select pg_is_in_recovery()' 2>/dev/null || true)"
  [[ "$recovery_state" == f ]] && break
  sleep 1
done
test "$recovery_state" = f
pre="$(docker exec -u postgres "$recovery" psql -U postgres -d postgres -Atqc "select count(*) from pitr_marker where name='pre-target'")"
post="$(docker exec -u postgres "$recovery" psql -U postgres -d postgres -Atqc "select count(*) from pitr_marker where name='post-target'")"
printf 'PITR_PRE_TARGET_COUNT=%s\nPITR_POST_TARGET_COUNT=%s\n' "$pre" "$post"
test "$pre" = 1 -a "$post" = 0

verified_marker="$(find "$work/stage" -maxdepth 1 -type f -name '*.offhost' | head -1)"
verified_source="${verified_marker%.offhost}"
touch -d '9 days ago' "$verified_marker"
CODESTRA_SHARED_WAL_STAGE="$work/stage" CODESTRA_SHARED_POSTGRES_STATE="$work/state" "$package/codestra-shared-postgres-prune-wal.sh" 7
test ! -e "$verified_marker" -a ! -e "$verified_source" -a -s "$failed_source"

printf '%s\n' 'POSTGRES_NON_ROOT=PASS' 'POSTGRES_STAGE_DIRECTORY=PASS' 'POSTGRES_OFFLOAD_SECRETS_ABSENT=PASS' \
  'WAL_ATOMIC_STAGE=PASS' 'WAL_ENCRYPTION=PASS' 'PORTABLE_CHECKSUMS=PASS' 'RESTIC_OFFHOST=PASS' \
  'RESTIC_READBACK=PASS' 'FAILED_OFFLOAD_RETENTION=PASS' 'VERIFIED_WAL_RETENTION=PASS' \
  'PG_BASEBACKUP_TAR_FETCH=PASS' 'BACKUP_MANIFEST=PASS' 'BASE_BACKUP_DECRYPTION=PASS' \
  'RESTORE_COMMAND=PASS' 'PITR_PRE_TARGET=PASS' 'PITR_POST_TARGET_ABSENT=PASS' \
  'SHARED_PITR_EXECUTION_REHEARSAL=PASS'
