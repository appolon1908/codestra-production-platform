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
metrics_state=/var/lib/codestra-shared-postgresql
mkdir -p "$metrics_state"
chmod 0700 "$metrics_state"
disk_used="$(df -P "$stage" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
[[ "$disk_used" =~ ^[0-9]+$ ]]
if (( disk_used >= 90 )); then
  printf 'critical WAL spool filesystem usage: %s%%\n' "$disk_used" >&2
  exit 1
fi

RESTIC_REPOSITORY="$(<"$authority/restic-repository")"
export RESTIC_PASSWORD_FILE="$authority/restic-password"
export RESTIC_CACHE_DIR=/opt/codestra/backups/postgresql-shared/.restic-cache
export RESTIC_REPOSITORY
if [[ -f "$authority/object-access-key-id" ]]; then AWS_ACCESS_KEY_ID="$(<"$authority/object-access-key-id")"; export AWS_ACCESS_KEY_ID; fi
if [[ -f "$authority/object-secret-access-key" ]]; then AWS_SECRET_ACCESS_KEY="$(<"$authority/object-secret-access-key")"; export AWS_SECRET_ACCESS_KEY; fi
if [[ -f "$authority/object-region" ]]; then AWS_DEFAULT_REGION="$(<"$authority/object-region")"; export AWS_DEFAULT_REGION; fi
shopt -s nullglob
for source_path in "$stage"/[0-9A-F]*; do
  [[ -f "$source_path" && ! -L "$source_path" ]]
  [[ "$source_path" == *.offhost ]] && continue
  wal_name="${source_path##*/}"
  [[ "$wal_name" =~ ^[0-9A-F]{24}(\.[0-9A-F]{8}\.backup)?$ ]]
  artifact="$spool/$wal_name.gpg"
  if [[ ! -s "$artifact" ]]; then
    temporary="$(mktemp "$spool/.${wal_name}.XXXXXX")"
    gpg --homedir "$authority/gpg" --batch --yes --trust-model always \
      --recipient "$recipient" --encrypt --output "$temporary" "$source_path"
    mv "$temporary" "$artifact"
    (cd "$spool" && sha256sum "$wal_name.gpg" >"$wal_name.gpg.sha256")
  fi
  (cd "$spool" && sha256sum -c "$wal_name.gpg.sha256" >/dev/null)
  restic backup --quiet --tag shared-postgresql-wal "$artifact" "$artifact.sha256"
  snapshot_id="$(restic snapshots --json --tag shared-postgresql-wal --path "$artifact" \
    | python3 -c 'import json,sys; values=json.load(sys.stdin); print(values[-1]["id"] if values else "")')"
  [[ "$snapshot_id" =~ ^[0-9a-f]{64}$ ]]
  expected_hash="$(awk 'NR==1 {print $1}' "$artifact.sha256")"
  remote_hash="$(restic dump "$snapshot_id" "$artifact" | sha256sum | awk '{print $1}')"
  [[ "$remote_hash" == "$expected_hash" ]]
  captured_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  expires_at="$(date -u -d "+${retention_days} days" +%Y-%m-%dT%H:%M:%SZ)"
  marker="$source_path.offhost"
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

CODESTRA_SHARED_WAL_STAGE="$stage" CODESTRA_SHARED_POSTGRES_STATE="$metrics_state" \
  /usr/local/sbin/codestra-shared-postgres-prune-wal.sh "$retention_days"
find "$spool" -maxdepth 1 -type f \( -name '*.gpg' -o -name '*.gpg.sha256' \) \
  -mtime "+$retention_days" -delete
restic forget --quiet --tag shared-postgresql-wal --keep-within "${retention_days}d"
