#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(id -u)" -eq 0

authority=/etc/codestra/secrets/shared-postgresql
stage=/var/spool/codestra/postgresql-shared/wal
spool=/opt/codestra/backups/postgresql-shared/wal
recipient="$(<"$authority/archive-recipient")"
mkdir -p "$spool"
chmod 0700 "$spool"

RESTIC_REPOSITORY="$(<"$authority/restic-repository")"
export RESTIC_PASSWORD_FILE="$authority/restic-password"
export RESTIC_CACHE_DIR=/opt/codestra/backups/postgresql-shared/.restic-cache
AWS_ACCESS_KEY_ID="$(<"$authority/object-access-key-id")"
AWS_SECRET_ACCESS_KEY="$(<"$authority/object-secret-access-key")"
AWS_DEFAULT_REGION="$(<"$authority/object-region")"
export RESTIC_REPOSITORY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
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
  restic snapshots --json --tag shared-postgresql-wal --path "$artifact" \
    | grep -q '"id"'
  touch "$source_path.offhost"
  touch "$spool/LAST_OFFHOST_SUCCESS"
done

retention_days="$(<"$authority/wal-retention-days")"
[[ "$retention_days" =~ ^[1-9][0-9]*$ ]]
find "$stage" -maxdepth 1 -type f -name '*.offhost' -mtime "+$retention_days" -print0 \
  | while IFS= read -r -d '' marker; do
      source_path="${marker%.offhost}"
      [[ "$source_path" == "$stage"/[0-9A-F]* && -f "$source_path" ]]
      find "$source_path" "$marker" -delete
    done
find "$spool" -maxdepth 1 -type f \( -name '*.gpg' -o -name '*.gpg.sha256' \) \
  -mtime "+$retention_days" -delete
restic forget --quiet --tag shared-postgresql-wal --keep-within "${retention_days}d"
