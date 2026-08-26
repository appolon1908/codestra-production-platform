#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(id -u)" -eq 0
authority=/etc/codestra/secrets/shared-postgresql
root=/opt/codestra/backups/postgresql-shared/base
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$root/$stamp"
mkdir -p "$destination"
chmod 0700 "$destination"

container="$(<"$authority/postgres-container")"
recipient="$(<"$authority/archive-recipient")"
temporary="$destination/base.tar.gpg.partial"
docker exec "$container" pg_basebackup -U "$(<"$authority/backup-role")" \
  -D - -Ft -X fetch -c fast -l "codestra-shared-$stamp" \
  | gpg --homedir "$authority/gpg" --batch --yes --trust-model always \
      --recipient "$recipient" --encrypt --output "$temporary"
mv "$temporary" "$destination/base.tar.gpg"
(cd "$destination" && sha256sum base.tar.gpg >SHA256SUMS)
(cd "$destination" && sha256sum -c SHA256SUMS >/dev/null)

RESTIC_REPOSITORY="$(<"$authority/restic-repository")"
export RESTIC_PASSWORD_FILE="$authority/restic-password"
export RESTIC_CACHE_DIR=/opt/codestra/backups/postgresql-shared/.restic-cache
AWS_ACCESS_KEY_ID="$(<"$authority/object-access-key-id")"
AWS_SECRET_ACCESS_KEY="$(<"$authority/object-secret-access-key")"
AWS_DEFAULT_REGION="$(<"$authority/object-region")"
export RESTIC_REPOSITORY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
restic backup --quiet --tag shared-postgresql-base "$destination"
restic forget --quiet --tag shared-postgresql-base --keep-weekly 8 --keep-monthly 12
printf '%s\n' "$stamp" >"$root/LAST_SUCCESS"
