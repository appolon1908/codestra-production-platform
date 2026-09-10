#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(id -u)" -eq 0
source_path="$1"
wal_name="$2"
[[ "$wal_name" =~ ^[0-9A-F]{24}(\.[0-9A-F]{8}\.backup)?$ ]]
[[ "$source_path" != *..* && -f "$source_path" ]]

spool=/opt/codestra/backups/kong-database/wal
recipient='Codestra Backup Recipient'
artifact="$spool/$wal_name.gpg"
object_access_key_file=/etc/codestra/backup/object-access-key-id
object_secret_key_file=/etc/codestra/backup/object-secret-access-key
object_region_file=/etc/codestra/backup/object-region
mkdir -p "$spool"
chmod 0700 "$spool"
if [[ ! -s "$artifact" ]]; then
  temporary="$(mktemp "$spool/.${wal_name}.XXXXXX")"
  trap 'rm -f "$temporary"' EXIT
  gpg --homedir /etc/codestra/backup-gpg --batch --yes --trust-model always \
    --recipient "$recipient" --encrypt --output "$temporary" "$source_path"
  mv "$temporary" "$artifact"
  sha256sum "$artifact" >"$artifact.sha256"
fi

for path in /etc/codestra/backup/restic-repository \
  /etc/codestra/backup/restic-password \
  "$object_access_key_file" "$object_secret_key_file" "$object_region_file"; do
  test -r "$path"
  test ! -L "$path"
done

export RESTIC_REPOSITORY="$(cat /etc/codestra/backup/restic-repository)"
export RESTIC_PASSWORD_FILE=/etc/codestra/backup/restic-password
export RESTIC_CACHE_DIR=/opt/codestra/backups/kong-database/.restic-cache
export AWS_ACCESS_KEY_ID="$(cat "$object_access_key_file")"
export AWS_SECRET_ACCESS_KEY="$(cat "$object_secret_key_file")"
export AWS_DEFAULT_REGION="$(cat "$object_region_file")"
restic backup --quiet --tag kong-database-wal "$artifact" "$artifact.sha256"
touch "$spool/LAST_OFFHOST_SUCCESS"
