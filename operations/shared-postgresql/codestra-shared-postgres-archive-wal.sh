#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(id -u)" -eq 0

authority="${CODESTRA_SHARED_POSTGRES_AUTHORITY:-/etc/codestra/secrets/shared-postgresql}"
stage="${CODESTRA_SHARED_WAL_STAGE:-/var/spool/codestra/postgresql-shared/wal}"
spool="${CODESTRA_SHARED_WAL_ARCHIVE:-/opt/codestra/backups/postgresql-shared/wal}"
[[ -d "$authority" && ! -L "$authority" && -d "$stage" && ! -L "$stage" ]]
recipient="$(<"$authority/archive-recipient")"
retention_days="$(<"$authority/wal-retention-days")"
[[ "$retention_days" =~ ^[1-9][0-9]*$ ]]
mkdir -p "$spool"
chmod 0700 "$spool"
metrics_state="${CODESTRA_SHARED_POSTGRES_STATE:-/var/lib/codestra-shared-postgresql}"
mkdir -p "$metrics_state"
chmod 0700 "$metrics_state"
disk_used="$(df -P "$stage" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
[[ "$disk_used" =~ ^[0-9]+$ ]]
if (( disk_used >= 90 )); then
  printf 'critical WAL spool filesystem usage: %s%%\n' "$disk_used" >&2
  printf '1\n' >"$metrics_state/wal_spool_disk_critical"
else
  printf '0\n' >"$metrics_state/wal_spool_disk_critical"
fi

RESTIC_REPOSITORY="$(<"$authority/restic-repository")"
export RESTIC_PASSWORD_FILE="$authority/restic-password"
export RESTIC_CACHE_DIR="${CODESTRA_SHARED_RESTIC_CACHE:-/opt/codestra/backups/postgresql-shared/.restic-cache}"
export RESTIC_REPOSITORY
if [[ -f "$authority/object-access-key-id" ]]; then AWS_ACCESS_KEY_ID="$(<"$authority/object-access-key-id")"; export AWS_ACCESS_KEY_ID; fi
if [[ -f "$authority/object-secret-access-key" ]]; then AWS_SECRET_ACCESS_KEY="$(<"$authority/object-secret-access-key")"; export AWS_SECRET_ACCESS_KEY; fi
if [[ -f "$authority/object-region" ]]; then AWS_DEFAULT_REGION="$(<"$authority/object-region")"; export AWS_DEFAULT_REGION; fi

restic_lock="${CODESTRA_SHARED_POSTGRES_RESTIC_LOCK:-/run/lock/codestra-shared-postgresql-restic.lock}"
install -d -m 0755 "$(dirname "$restic_lock")"
exec 9>"$restic_lock"
flock -w 300 9

shopt -s nullglob
for source_path in "$stage"/[0-9A-F]*; do
  [[ -f "$source_path" && ! -L "$source_path" ]]
  [[ "$source_path" == *.offhost ]] && continue
  wal_name="${source_path##*/}"
  [[ "$wal_name" =~ ^([0-9A-F]{24}(\.[0-9A-F]{8}\.backup)?|[0-9A-F]{8}\.history)$ ]]
  marker="$source_path.offhost"
  if [[ -f "$marker" && ! -L "$marker" ]] \
    && grep -qx 'EVIDENCE_TYPE=WAL_OFFHOST' "$marker" \
    && grep -qx 'STATUS=PASS' "$marker"; then
    recorded_artifact="$(awk -F= '$1=="ARTIFACT_PATH"{print substr($0,index($0,"=")+1)}' "$marker")"
    recorded_hash="$(awk -F= '$1=="ARTIFACT_SHA256"{print $2}' "$marker")"
    if [[ "$recorded_artifact" == "$spool"/* && -f "$recorded_artifact" && ! -L "$recorded_artifact" \
      && "$recorded_hash" =~ ^[0-9a-f]{64}$ \
      && "$(sha256sum "$recorded_artifact" | awk '{print $1}')" == "$recorded_hash" ]]; then
      continue
    fi
  fi

  artifact="$spool/$wal_name.gpg"
  if [[ ! -s "$artifact" ]]; then
    temporary="$(mktemp "$spool/.${wal_name}.XXXXXX")"
    gpg --homedir "$authority/gpg" --batch --yes --trust-model always \
      --recipient "$recipient" --encrypt --output "$temporary" "$source_path"
    mv "$temporary" "$artifact"
    (cd "$spool" && sha256sum "$wal_name.gpg" >"$wal_name.gpg.sha256")
  fi
  (cd "$spool" && sha256sum -c "$wal_name.gpg.sha256" >/dev/null)

  backup_json="$(mktemp "$spool/.${wal_name}.restic.XXXXXX")"
  index_json="$(mktemp "$spool/.${wal_name}.index.XXXXXX")"
  trap 'find "$backup_json" "$index_json" -delete 2>/dev/null || true' RETURN
  restic backup --json --tag shared-postgresql-wal "$artifact" "$artifact.sha256" >"$backup_json"
  snapshot_id="$(python3 - "$backup_json" <<'PY'
import json
import sys
from pathlib import Path

snapshot_id = ""
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.strip():
        continue
    value = json.loads(raw)
    if value.get("message_type") == "summary" and value.get("snapshot_id"):
        snapshot_id = value["snapshot_id"]
if not snapshot_id:
    raise SystemExit("restic backup produced no summary snapshot ID")
print(snapshot_id)
PY
)"
  [[ "$snapshot_id" =~ ^[0-9a-f]{64}$ ]]
  restic ls --json "$snapshot_id" >"$index_json"
  remote_path="$(python3 - "$index_json" "$artifact" <<'PY'
import json
import sys
from pathlib import Path, PurePosixPath

name = PurePosixPath(sys.argv[2]).name
matches = []
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.strip():
        continue
    value = json.loads(raw)
    if value.get("struct_type") == "node" and value.get("type") == "file":
        candidate = value.get("path", "")
        if PurePosixPath(candidate).name == name:
            matches.append(candidate)
if len(matches) != 1:
    raise SystemExit(f"expected exactly one restic WAL path for {name}: {matches}")
print(matches[0])
PY
)"
  expected_hash="$(awk 'NR==1 {print $1}' "$artifact.sha256")"
  remote_hash="$(restic dump "$snapshot_id" "$remote_path" | sha256sum | awk '{print $1}')"
  [[ "$remote_hash" == "$expected_hash" ]]
  find "$backup_json" "$index_json" -delete
  trap - RETURN

  captured_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  expires_at="$(date -u -d "+${retention_days} days" +%Y-%m-%dT%H:%M:%SZ)"
  marker_tmp="${marker}.partial"
  cat >"$marker_tmp" <<EOF
CHANGE_ID=$(<"$authority/current-change-id")
EVIDENCE_TYPE=WAL_OFFHOST
STATUS=PASS
CAPTURED_AT=$captured_at
SOURCE_HOST=$(hostname -f)
ARTIFACT_PATH=$artifact
ARTIFACT_SHA256=$expected_hash
EXPIRES_AT=$expires_at
REMOTE_SNAPSHOT_ID=$snapshot_id
EOF
  chmod 0600 "$marker_tmp"
  sync -d "$marker_tmp"
  mv "$marker_tmp" "$marker"
  sync -d "$stage"
  touch "$spool/LAST_OFFHOST_SUCCESS"
done

prune_helper="${CODESTRA_SHARED_POSTGRES_PRUNE_HELPER:-/usr/local/sbin/codestra-shared-postgres-prune-wal.sh}"
[[ -x "$prune_helper" ]]
CODESTRA_SHARED_WAL_STAGE="$stage" CODESTRA_SHARED_POSTGRES_STATE="$metrics_state" \
  "$prune_helper" "$retention_days"
find "$spool" -maxdepth 1 -type f \( -name '*.gpg' -o -name '*.gpg.sha256' \) \
  -mtime "+$retention_days" -delete
restic forget --quiet --tag shared-postgresql-wal --keep-within "${retention_days}d"
