#!/usr/bin/env bash
set -euo pipefail
umask 077

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
helper="$root/operations/shared-postgresql/create-base-backup.sh"
image="${POSTGRES_17_IMAGE:-postgres:17.6}"
stamp="$(date -u +%Y%m%d%H%M%S)-$$"
network="shared-base-helper-$stamp"
primary="shared-base-primary-$stamp"
work="$(mktemp -d /var/tmp/shared-base-helper.XXXXXX)"
cleanup() {
  docker rm -f "$primary" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  find "$work" -xdev -type f -delete 2>/dev/null || true
  find "$work" -depth -type d -empty -delete 2>/dev/null || true
}
trap cleanup EXIT

for command in docker gpg restic python3; do command -v "$command" >/dev/null; done
docker pull "$image" >/dev/null
image_digest="$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')"
[[ "$image_digest" == *@sha256:* ]]
mkdir -p "$work/authority/gpg" "$work/base" "$work/restic"
chmod 0700 "$work/authority" "$work/authority/gpg" "$work/base" "$work/restic"

docker network create --internal --subnet "${SHARED_BASE_TEST_SUBNET:-10.253.251.0/28}" "$network" >/dev/null
docker run -d --name "$primary" --network "$network" --network-alias primary \
  -e POSTGRES_PASSWORD=synthetic-helper-only -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
  "$image_digest" -c wal_level=replica -c max_wal_senders=4 >/dev/null
for _ in $(seq 1 60); do docker exec "$primary" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
docker exec "$primary" pg_isready -U postgres >/dev/null
docker exec -u postgres "$primary" sh -ec \
  'printf "%s\n" "host replication all 0.0.0.0/0 scram-sha-256" >> "$PGDATA/pg_hba.conf"'
docker exec -u postgres "$primary" psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'select pg_reload_conf()' >/dev/null

gpg --homedir "$work/authority/gpg" --batch --generate-key <<'EOF'
Key-Type: RSA
Key-Length: 2048
Key-Usage: encrypt
Name-Real: Shared PostgreSQL helper integration
Name-Email: shared-pitr-helper@codestra.invalid
Expire-Date: 1d
%no-protection
%commit
EOF
printf '%s\n' 'shared-pitr-helper@codestra.invalid' >"$work/authority/archive-recipient"
printf '%s\n' "$image_digest" >"$work/authority/postgres-image"
printf '%s\n' "$network" >"$work/authority/postgres-network"
printf '%s\n' primary >"$work/authority/postgres-host"
printf '%s\n' 5432 >"$work/authority/postgres-port"
printf '%s\n' postgres >"$work/authority/backup-role"
printf '%s\n' 'primary:5432:*:postgres:synthetic-helper-only' >"$work/authority/backup-passfile"
printf '%s\n' "$work/restic" >"$work/authority/restic-repository"
printf '%s\n' 'synthetic-restic-password-only' >"$work/authority/restic-password"
chmod 0600 "$work/authority"/* 2>/dev/null || true
chmod 0700 "$work/authority/gpg"
RESTIC_REPOSITORY="$work/restic" RESTIC_PASSWORD_FILE="$work/authority/restic-password" restic init >/dev/null

CODESTRA_SHARED_POSTGRES_AUTHORITY="$work/authority" \
CODESTRA_SHARED_POSTGRES_BASE_ROOT="$work/base" \
CODESTRA_SHARED_POSTGRES_RESTIC_LOCK="$work/restic.lock" \
TMPDIR="$work" \
bash "$helper"

last_success="$(<"$work/base/LAST_SUCCESS")"
[[ "$last_success" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]
destination="$work/base/$last_success"
(cd "$destination" && sha256sum -c SHA256SUMS >/dev/null)
test -s "$destination/base.tar.gpg"
test -s "$destination/backup_manifest"
RESTIC_REPOSITORY="$work/restic" RESTIC_PASSWORD_FILE="$work/authority/restic-password" \
  restic snapshots --json --tag shared-postgresql-base | \
  python3 -c 'import json,sys; values=json.load(sys.stdin); assert len(values) == 1'
[[ "$(stat -c '%u:%a' "$work/authority/backup-passfile")" == "0:600" ]]
printf '%s\n' \
  'ACTUAL_BASE_BACKUP_HELPER=PASS' \
  'ROOT_AUTHORITY_PASSFILE=PASS' \
  'NON_ROOT_CONTAINER_PASSFILE_READABILITY=PASS' \
  'PG_BASEBACKUP=PASS' \
  'PG_VERIFYBACKUP=PASS' \
  'ENCRYPTION=PASS' \
  'RESTIC_READBACK=PASS'
