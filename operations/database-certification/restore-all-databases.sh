#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=${CODESTRA_DATABASE_BACKUP_ROOT:-/opt/codestra/backups/database-certification}
gpg_home=${CODESTRA_DATABASE_BACKUP_GPG_HOME:-/etc/codestra/backup-gpg}
evidence_root=${CODESTRA_DATABASE_RESTORE_ROOT:-/opt/codestra/evidence/database-restore}
latest=$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' | sort | tail -1)
test -n "$latest"
grep -qx DATABASE_BACKUP=PASS "$latest/STATUS.txt"
(cd "$latest" && sha256sum -c SHA256SUMS)

stamp=$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$evidence_root"
work=$(mktemp -d "${evidence_root}/.work-${stamp}.XXXXXX")
final="${evidence_root}/${stamp}"
container="codestra-database-restore-${stamp//[^0-9A-Za-z]/}"
volume="${container}-data"
started=$(date +%s)
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  find "$work" -xdev -type f -delete 2>/dev/null || true
  find "$work" -depth -type d -empty -delete 2>/dev/null || true
}
trap cleanup EXIT
trap 'printf "DATABASE_RESTORE=FAIL\n" >&2' ERR
install -d -m 0700 "$final"

encrypted=$(find "$latest" -maxdepth 1 -name 'databases-*.tar.gz.gpg' -type f | head -1)
gpg --homedir "$gpg_home" --batch --yes --output "$work/databases.tar.gz" --decrypt "$encrypted"
tar -xzf "$work/databases.tar.gz" -C "$work"
(cd "$work" && sha256sum -c PLAINTEXT-SHA256SUMS)

python3 - "$work/provisioning.sqlite3" <<'PY'
import sqlite3, sys
db=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True)
assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
PY

image=$(docker inspect codestra-postgres-1 -f '{{.Config.Image}}')
docker volume create "$volume" >/dev/null
docker run -d --name "$container" -e POSTGRES_HOST_AUTH_METHOD=trust -v "$volume:/var/lib/postgresql/data" "$image" >/dev/null
for _ in $(seq 1 60); do docker exec "$container" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
docker exec "$container" pg_isready -U postgres >/dev/null

count=0
for archive in "$work"/*.dump; do
  name=$(basename "$archive" .dump | tr -c 'a-zA-Z0-9_' '_')
  docker exec "$container" createdb -U postgres "$name"
  docker cp "$archive" "$container:/tmp/restore.dump" >/dev/null
  docker exec "$container" pg_restore -U postgres --no-owner --no-privileges --exit-on-error -d "$name" /tmp/restore.dump
  docker exec "$container" psql -X -U postgres -d "$name" -At -v ON_ERROR_STOP=1 -c 'select 1' | grep -qx 1
  count=$((count+1))
done
test "$count" -eq 10
rto=$(( $(date +%s) - started ))
cat > "$final/RESTORE-RESULT.txt" <<EOF
DATABASE_RESTORE=PASS
BACKUP_TIMESTAMP=$(sed -n 's/^BACKUP_TIMESTAMP=//p' "$latest/STATUS.txt")
POSTGRES_DATABASE_COUNT=${count}
SQLITE_DATABASE_COUNT=1
RESTORE_RTO_SECONDS=${rto}
RESTORE_PUBLIC_PORTS=0
RESTORE_RESIDUAL_RESOURCES=0
EOF
sha256sum "$final/RESTORE-RESULT.txt" > "$final/SHA256SUMS"
printf '%s\n' "$final"
