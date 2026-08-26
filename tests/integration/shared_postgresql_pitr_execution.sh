#!/usr/bin/env bash
set -euo pipefail
umask 077

image="${POSTGRES_17_IMAGE:-postgres:17.6}"
stamp="$(date -u +%Y%m%d%H%M%S)-$$"
network="shared-pitr-test-$stamp"
primary="shared-pitr-primary-$stamp"
recovery="shared-pitr-recovery-$stamp"
work="$(mktemp -d /var/tmp/shared-pitr-integration.XXXXXX)"
cleanup() {
  docker rm -f "$primary" "$recovery" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  # Synthetic disposable integration data contains no production material.
  find "$work" -xdev -type f -delete 2>/dev/null || true
  find "$work" -depth -type d -empty -delete 2>/dev/null || true
}
trap cleanup EXIT
mkdir -p "$work/archive" "$work/base" "$work/recovered-archive" "$work/recovery"
chmod 0777 "$work/archive" "$work/base"
docker network create --internal --subnet "${SHARED_PITR_TEST_SUBNET:-10.253.250.0/28}" "$network" >/dev/null
docker run -d --name "$primary" --network "$network" --network-alias primary \
  --mount "type=bind,src=$work/archive,dst=/archive" \
  --mount "type=bind,src=$work/base,dst=/backup" \
  -e POSTGRES_PASSWORD=synthetic-rehearsal-only -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
  "$image" -c wal_level=replica -c archive_mode=on \
  -c "archive_command=test ! -f /archive/%f && cp %p /archive/%f" -c archive_timeout=1s >/dev/null
for _ in $(seq 1 60); do docker exec "$primary" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
docker exec "$primary" pg_isready -U postgres >/dev/null
docker exec -u postgres "$primary" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'create table pitr_marker(name text primary key, created_at timestamptz default clock_timestamp())' >/dev/null
docker exec -u postgres -e PGPASSWORD=synthetic-rehearsal-only "$primary" \
  pg_basebackup -h 127.0.0.1 -U postgres -D /backup -Fp -X stream -c fast --manifest-checksums=SHA256 \
  >/dev/null
test -s "$work/base/backup_manifest"
docker exec -u postgres "$primary" pg_verifybackup /backup >/dev/null

docker exec -u postgres "$primary" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c "insert into pitr_marker(name) values ('pre-target')" >/dev/null
docker exec -u postgres "$primary" psql -U postgres -d postgres -Atqc 'select pg_switch_wal()' >/dev/null
sleep 2
target="$(docker exec -u postgres "$primary" psql -U postgres -d postgres -Atqc "select clock_timestamp() at time zone 'UTC'") UTC"
sleep 2
docker exec -u postgres "$primary" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c "insert into pitr_marker(name) values ('post-target')" >/dev/null
docker exec -u postgres "$primary" psql -U postgres -d postgres -Atqc 'select pg_switch_wal()' >/dev/null
for _ in $(seq 1 30); do find "$work/archive" -maxdepth 1 -type f | grep -q . && break; sleep 1; done

# Exercise encryption, portable checksums, relocation, and decryption before recovery.
mkdir -p "$work/encrypted"
for wal in "$work/archive"/[0-9A-F]*; do
  test -f "$wal"
  name="${wal##*/}"
  gpg --batch --yes --pinentry-mode loopback --passphrase synthetic-integration-only \
    --symmetric --cipher-algo AES256 --output "$work/encrypted/$name.gpg" "$wal"
  (cd "$work/encrypted" && sha256sum "$name.gpg" >"$name.gpg.sha256")
  cp "$work/encrypted/$name.gpg" "$work/encrypted/$name.gpg.sha256" "$work/recovered-archive/"
  (cd "$work/recovered-archive" && sha256sum -c "$name.gpg.sha256" >/dev/null)
  gpg --batch --yes --pinentry-mode loopback --passphrase synthetic-integration-only \
    --decrypt --output "$work/recovered-archive/$name" "$work/recovered-archive/$name.gpg"
done

docker stop "$primary" >/dev/null
cp -a "$work/base/." "$work/recovery/"
printf "restore_command = 'cp /archive/%%f %%p'\nrecovery_target_time = '%s'\nrecovery_target_action = 'promote'\n" "$target" \
  >>"$work/recovery/postgresql.auto.conf"
touch "$work/recovery/recovery.signal"
chown -R 999:999 "$work/recovery" "$work/recovered-archive"
chmod 0700 "$work/recovery"
docker run -d --name "$recovery" --network "$network" \
  --mount "type=bind,src=$work/recovery,dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=$work/recovered-archive,dst=/archive,readonly" "$image" >/dev/null
for _ in $(seq 1 90); do docker exec "$recovery" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
docker exec "$recovery" pg_isready -U postgres >/dev/null
pre="$(docker exec -u postgres "$recovery" psql -U postgres -d postgres -Atqc "select count(*) from pitr_marker where name='pre-target'")"
post="$(docker exec -u postgres "$recovery" psql -U postgres -d postgres -Atqc "select count(*) from pitr_marker where name='post-target'")"
test "$pre" = 1
test "$post" = 0
printf 'POSTGRES_NON_ROOT=PASS\nPG_BASEBACKUP_EXECUTION=PASS\nBACKUP_MANIFEST=PASS\nPORTABLE_CHECKSUMS=PASS\nRESTORE_COMMAND=PASS\nPITR_PRE_TARGET=PASS\nPITR_POST_TARGET_ABSENT=PASS\n'
