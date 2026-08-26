#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(id -u)" -eq 0
authority="${CODESTRA_SHARED_POSTGRES_AUTHORITY:-/etc/codestra/secrets/shared-postgresql}"
root="${CODESTRA_SHARED_POSTGRES_BASE_ROOT:-/opt/codestra/backups/postgresql-shared/base}"
[[ -d "$authority" && ! -L "$authority" ]]
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$root/$stamp"
work="$(mktemp -d "${TMPDIR:-/var/tmp}/codestra-shared-base.XXXXXX")"
partial="$destination/base.tar.gpg.partial"
cleanup() {
  find "$work" -xdev -type f -exec shred -u -- {} + 2>/dev/null || true
  find "$work" -depth -type d -empty -delete 2>/dev/null || true
  find "$partial" -delete 2>/dev/null || true
}
trap cleanup EXIT
mkdir -p "$destination" "$work/tar" "$work/verify"
chmod 0700 "$destination" "$work" "$work/tar" "$work/verify"

image="$(<"$authority/postgres-image")"; network="$(<"$authority/postgres-network")"
host="$(<"$authority/postgres-host")"; port="$(<"$authority/postgres-port")"
role="$(<"$authority/backup-role")"; passfile="$authority/backup-passfile"
recipient="$(<"$authority/archive-recipient")"
[[ "$image" == *@sha256:* && "$port" =~ ^[0-9]+$ && -f "$passfile" && ! -L "$passfile" ]]
postgres_uid="$(docker run --rm --network none --entrypoint id "$image" -u postgres)"
postgres_gid="$(docker run --rm --network none --entrypoint id "$image" -g postgres)"
chown "$postgres_uid:$postgres_gid" "$work/tar"
install -m 0600 "$passfile" "$work/pgpass"
chown "$postgres_uid:$postgres_gid" "$work/pgpass"
docker run --rm --network "$network" --read-only --user "$postgres_uid:$postgres_gid" \
  --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e PGPASSFILE=/run/secrets/pgpass \
  -v "$work/pgpass:/run/secrets/pgpass:ro" -v "$work/tar:/backup" \
  --entrypoint pg_basebackup "$image" -h "$host" -p "$port" -U "$role" \
  -D /backup -Ft -X fetch -c fast -l "codestra-shared-$stamp" --manifest-checksums=SHA256
test -s "$work/tar/base.tar" -a -s "$work/tar/backup_manifest"
tar -xf "$work/tar/base.tar" -C "$work/verify"
find "$work/verify/pg_wal" -maxdepth 1 -type f -name '[0-9A-F]*' | grep -q .
cp "$work/tar/backup_manifest" "$work/verify/backup_manifest"
chown -R "$postgres_uid:$postgres_gid" "$work/verify"
docker run --rm --network none --read-only --user "$postgres_uid:$postgres_gid" \
  --cap-drop ALL --security-opt no-new-privileges:true -v "$work/verify:/backup:ro" \
  --entrypoint pg_verifybackup "$image" /backup

tar --numeric-owner -C "$work/tar" -cf "$work/base.tar" base.tar backup_manifest
cp "$work/tar/backup_manifest" "$destination/backup_manifest"
printf 'BACKUP_TIMESTAMP=%s\nPOSTGRES_IMAGE=%s\nFORMAT=tar\nWAL_METHOD=fetch\n' "$stamp" "$image" >"$destination/metadata.env"
gpg --homedir "$authority/gpg" --batch --yes --trust-model always --recipient "$recipient" \
  --encrypt --output "$partial" "$work/base.tar"
mv "$partial" "$destination/base.tar.gpg"
(cd "$destination" && sha256sum base.tar.gpg backup_manifest metadata.env >SHA256SUMS)
(cd "$destination" && sha256sum -c SHA256SUMS >/dev/null)

RESTIC_REPOSITORY="$(<"$authority/restic-repository")"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE="$authority/restic-password"
export RESTIC_CACHE_DIR="${CODESTRA_SHARED_RESTIC_CACHE:-$root/.restic-cache}"
if [[ -f "$authority/object-access-key-id" ]]; then AWS_ACCESS_KEY_ID="$(<"$authority/object-access-key-id")"; export AWS_ACCESS_KEY_ID; fi
if [[ -f "$authority/object-secret-access-key" ]]; then AWS_SECRET_ACCESS_KEY="$(<"$authority/object-secret-access-key")"; export AWS_SECRET_ACCESS_KEY; fi
if [[ -f "$authority/object-region" ]]; then AWS_DEFAULT_REGION="$(<"$authority/object-region")"; export AWS_DEFAULT_REGION; fi
backup_result="$(restic backup --quiet --json --tag shared-postgresql-base "$destination")"
snapshot_ref="$(python3 -c 'import json,sys
value=""
for line in sys.stdin:
    if line.strip():
        value=json.loads(line).get("snapshot_id", value)
print(value)' <<<"$backup_result")"
[[ "$snapshot_ref" =~ ^[0-9a-f]{8,64}$ ]]
snapshot_id="$(restic snapshots --json "$snapshot_ref" | python3 -c 'import json,sys; values=json.load(sys.stdin); print(values[0]["id"] if len(values) == 1 else "")')"
[[ "$snapshot_id" =~ ^[0-9a-f]{64}$ ]]
for name in base.tar.gpg backup_manifest metadata.env SHA256SUMS; do
  expected="$(sha256sum "$destination/$name" | awk '{print $1}')"
  actual="$(restic dump "$snapshot_id" "$destination/$name" | sha256sum | awk '{print $1}')"
  [[ "$actual" == "$expected" ]]
done
restic forget --quiet --tag shared-postgresql-base --keep-weekly 8 --keep-monthly 12
printf '%s\n' "$stamp" >"$root/LAST_SUCCESS"
