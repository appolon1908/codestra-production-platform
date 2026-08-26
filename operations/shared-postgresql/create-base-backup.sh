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
mkdir -p "$destination" "$work/data"
chmod 0700 "$destination" "$work" "$work/data"

safe_root_secret() {
  local path="$1" mode owner
  [[ -f "$path" && ! -L "$path" && -s "$path" ]] || return 1
  mode="$(stat -c '%a' "$path")"; owner="$(stat -c '%u' "$path")"
  [[ "$owner" == 0 && $((8#$mode & 077)) -eq 0 ]]
}

image="$(<"$authority/postgres-image")"; network="$(<"$authority/postgres-network")"
host="$(<"$authority/postgres-host")"; port="$(<"$authority/postgres-port")"
role="$(<"$authority/backup-role")"; passfile="$authority/backup-passfile"
recipient="$(<"$authority/archive-recipient")"
[[ "$image" == *@sha256:* && "$port" =~ ^[0-9]+$ ]]
safe_root_secret "$passfile"
postgres_uid="$(docker run --rm --network none --entrypoint id "$image" -u postgres)"
postgres_gid="$(docker run --rm --network none --entrypoint id "$image" -g postgres)"
[[ "$postgres_uid" =~ ^[0-9]+$ && "$postgres_gid" =~ ^[0-9]+$ ]]
chown "$postgres_uid:$postgres_gid" "$work/data"
runtime_passfile="$work/pgpass"
install -m 0600 -o "$postgres_uid" -g "$postgres_gid" "$passfile" "$runtime_passfile"

# Prove the exact non-root container identity can read the runtime credential copy
# before starting a potentially expensive base backup. The root-owned authority
# file itself is never mounted into the PostgreSQL utility container.
docker run --rm --network none --read-only --user "$postgres_uid:$postgres_gid" \
  --cap-drop ALL --security-opt no-new-privileges:true \
  -e PGPASSFILE=/run/secrets/pgpass -v "$runtime_passfile:/run/secrets/pgpass:ro" \
  --entrypoint sh "$image" -ec 'test -r "$PGPASSFILE"; test "$(stat -c %a "$PGPASSFILE")" = 600'

docker run --rm --network "$network" --read-only --user "$postgres_uid:$postgres_gid" \
  --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e PGPASSFILE=/run/secrets/pgpass \
  -v "$runtime_passfile:/run/secrets/pgpass:ro" -v "$work/data:/backup" \
  --entrypoint pg_basebackup "$image" -h "$host" -p "$port" -U "$role" \
  -D /backup -Fp -X stream -c fast -l "codestra-shared-$stamp" --manifest-checksums=SHA256
test -s "$work/data/backup_manifest"
docker run --rm --network none --read-only --user "$postgres_uid:$postgres_gid" \
  --cap-drop ALL --security-opt no-new-privileges:true -v "$work/data:/backup:ro" \
  --entrypoint pg_verifybackup "$image" /backup

tar --numeric-owner -C "$work/data" -cf "$work/base.tar" .
cp "$work/data/backup_manifest" "$destination/backup_manifest"
printf 'BACKUP_TIMESTAMP=%s\nPOSTGRES_IMAGE=%s\nWAL_METHOD=stream\n' "$stamp" "$image" >"$destination/metadata.env"
gpg --homedir "$authority/gpg" --batch --yes --trust-model always --recipient "$recipient" \
  --encrypt --output "$partial" "$work/base.tar"
mv "$partial" "$destination/base.tar.gpg"
(cd "$destination" && sha256sum base.tar.gpg backup_manifest metadata.env >SHA256SUMS)
(cd "$destination" && sha256sum -c SHA256SUMS >/dev/null)

RESTIC_REPOSITORY="$(<"$authority/restic-repository")"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE="$authority/restic-password"
export RESTIC_CACHE_DIR="$root/.restic-cache"
if [[ -f "$authority/object-access-key-id" ]]; then AWS_ACCESS_KEY_ID="$(<"$authority/object-access-key-id")"; export AWS_ACCESS_KEY_ID; fi
if [[ -f "$authority/object-secret-access-key" ]]; then AWS_SECRET_ACCESS_KEY="$(<"$authority/object-secret-access-key")"; export AWS_SECRET_ACCESS_KEY; fi
if [[ -f "$authority/object-region" ]]; then AWS_DEFAULT_REGION="$(<"$authority/object-region")"; export AWS_DEFAULT_REGION; fi
restic_lock="${CODESTRA_SHARED_POSTGRES_RESTIC_LOCK:-/run/lock/codestra-shared-postgresql-restic.lock}"
install -d -m 0755 "$(dirname "$restic_lock")"
exec 9>"$restic_lock"
flock -w 300 9

backup_json="$work/restic-backup.jsonl"
restic backup --json --tag shared-postgresql-base "$destination" >"$backup_json"
snapshot_id="$(python3 - "$backup_json" <<'PY'
import json
import sys
from pathlib import Path

summary = None
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.strip():
        continue
    value = json.loads(raw)
    if value.get("message_type") == "summary" and value.get("snapshot_id"):
        summary = value
if summary is None:
    raise SystemExit("restic backup produced no summary snapshot ID")
print(summary["snapshot_id"])
PY
)"
[[ "$snapshot_id" =~ ^[0-9a-f]{64}$ ]]

# Do not assume how a restic version represents an absolute source path. Read the
# exact snapshot index, require one matching basename, and dump that indexed path.
restic_index="$work/restic-index.jsonl"
restic ls --json "$snapshot_id" >"$restic_index"
for name in base.tar.gpg backup_manifest metadata.env SHA256SUMS; do
  remote_path="$(python3 - "$restic_index" "$name" <<'PY'
import json
import sys
from pathlib import PurePosixPath, Path

matches = []
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.strip():
        continue
    value = json.loads(raw)
    if value.get("struct_type") != "node" or value.get("type") != "file":
        continue
    path = value.get("path", "")
    if PurePosixPath(path).name == sys.argv[2]:
        matches.append(path)
if len(matches) != 1:
    raise SystemExit(f"expected exactly one restic path for {sys.argv[2]}: {matches}")
print(matches[0])
PY
)"
  expected="$(sha256sum "$destination/$name" | awk '{print $1}')"
  actual="$(restic dump "$snapshot_id" "$remote_path" | sha256sum | awk '{print $1}')"
  [[ "$actual" == "$expected" ]]
done
restic forget --quiet --tag shared-postgresql-base --keep-weekly 8 --keep-monthly 12
printf '%s\n' "$stamp" >"$root/LAST_SUCCESS"
