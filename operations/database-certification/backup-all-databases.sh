#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=${CODESTRA_DATABASE_BACKUP_ROOT:-/opt/codestra/backups/database-certification}
gpg_home=${CODESTRA_DATABASE_BACKUP_GPG_HOME:-/etc/codestra/backup-gpg}
gpg_recipient=${CODESTRA_DATABASE_BACKUP_GPG_RECIPIENT:-Codestra Backup Recipient}
remote=${CODESTRA_DATABASE_BACKUP_REMOTE:-}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$backup_root"
work=$(mktemp -d "${backup_root}/.work-${stamp}.XXXXXX")
archive="${work}.tar.gz"
final="${backup_root}/${stamp}"

cleanup() {
  find "$work" -xdev -type f -delete 2>/dev/null || true
  rmdir "$work" 2>/dev/null || true
  rm -f -- "$archive"
}
trap cleanup EXIT
trap 'printf "DATABASE_BACKUP=FAIL\n" >&2' ERR

install -d -m 0700 "$final"
command -v docker >/dev/null
command -v gpg >/dev/null
command -v sha256sum >/dev/null

dump() {
  local container=$1 user=$2 database=$3 output=$4
  test "$(docker inspect -f '{{.State.Status}}' "$container")" = running
  docker exec "$container" pg_isready -U "$user" -d "$database" >/dev/null
  docker exec "$container" pg_dump -U "$user" -d "$database" -Fc > "$work/$output.dump"
  test -s "$work/$output.dump"
  docker exec "$container" psql -X -U "$user" -d "$database" -At -v ON_ERROR_STOP=1 \
    -c "select current_setting('server_version'),pg_is_in_recovery(),count(*) from information_schema.tables where table_schema='public'" \
    > "$work/$output.catalog"
}

dump codestra-postgres-1 postgres codestra_odoo shared-odoo
dump codestra-postgres-1 postgres codestra_middleware shared-middleware
dump codestra-postgres-1 postgres codestra_n8n shared-n8n
dump codestra-postgres-1 postgres control_plane shared-control-plane
dump codestra-kong-kong-db-1 kong kong kong
dump codestra-identity-identity-db-1 keycloak keycloak identity
dump codestra-websocket-gateway-postgres-1 codestra_realtime codestra_realtime websocket-primary
dump codestra-websocket-standby-031447a-postgres-1 codestra_realtime codestra_realtime websocket-standby-independent
dump codestra-reseller-portal-postgres-1 reseller_portal reseller_portal reseller-portal
dump codestra-sms-api-postgres-1 codestra_sms codestra_sms sms-api

docker exec -i codestra-provisioning-service-provisioning-service-1 python - <<'PY'
import os, sqlite3
source = sqlite3.connect(f"file:{os.environ['STATE_DATABASE_PATH']}?mode=ro", uri=True)
target = sqlite3.connect('/var/lib/codestra/provisioning-certification.sqlite3')
source.backup(target)
assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
target.close(); source.close()
PY
docker cp codestra-provisioning-service-provisioning-service-1:/var/lib/codestra/provisioning-certification.sqlite3 "$work/provisioning.sqlite3"
docker exec codestra-provisioning-service-provisioning-service-1 rm -f /var/lib/codestra/provisioning-certification.sqlite3
test -s "$work/provisioning.sqlite3"

(
  cd "$work"
  sha256sum ./* > PLAINTEXT-SHA256SUMS
  sha256sum -c PLAINTEXT-SHA256SUMS
  tar -czf "$archive" .
)
gpg --homedir "$gpg_home" --batch --yes --trust-model always \
  --recipient "$gpg_recipient" --encrypt \
  --output "$final/databases-${stamp}.tar.gz.gpg" "$archive"
(
  cd "$final"
  sha256sum "databases-${stamp}.tar.gz.gpg" > SHA256SUMS
  sha256sum -c SHA256SUMS
)

offhost=PENDING
if [[ -n "$remote" ]]; then
  scp -q -o BatchMode=yes -o IdentitiesOnly=yes \
    "$final/databases-${stamp}.tar.gz.gpg" "$final/SHA256SUMS" "$remote/$stamp/"
  offhost=PASS
fi
cat > "$final/STATUS.txt" <<EOF
DATABASE_BACKUP=PASS
BACKUP_TIMESTAMP=${stamp}
DATABASE_DUMP_COUNT=10
SQLITE_BACKUP_COUNT=1
CHECKSUM=PASS
ENCRYPTION=PASS
OFFHOST_COPY=${offhost}
EOF
sha256sum "$final/STATUS.txt" > "$final/EVIDENCE-SHA256SUMS"
printf '%s\n' "$final"
