#!/usr/bin/env bash
set -euo pipefail
umask 077

backup_root=${CODESTRA_DATABASE_BACKUP_ROOT:-/opt/codestra/backups/database-certification}
gpg_home=${CODESTRA_DATABASE_BACKUP_GPG_HOME:-/etc/codestra/backup-gpg}
evidence_root=${CODESTRA_DATABASE_RESTORE_ROOT:-/opt/codestra/evidence/database-restore}

select_latest_completed_backup() {
  local candidate encrypted_count
  while IFS= read -r candidate; do
    [[ -f "$candidate/STATUS.txt" && -f "$candidate/SHA256SUMS" && -f "$candidate/EVIDENCE-SHA256SUMS" ]] || continue
    grep -qx DATABASE_BACKUP=PASS "$candidate/STATUS.txt" || continue
    grep -qx CHECKSUM=PASS "$candidate/STATUS.txt" || continue
    grep -qx ENCRYPTION=PASS "$candidate/STATUS.txt" || continue
    (cd "$candidate" && sha256sum -c SHA256SUMS >/dev/null && sha256sum -c EVIDENCE-SHA256SUMS >/dev/null) || continue
    encrypted_count=$(find "$candidate" -maxdepth 1 -name 'databases-*.tar.gz.gpg' -type f | wc -l)
    [[ "$encrypted_count" -eq 1 ]] || continue
    printf '%s\n' "$candidate"
    return 0
  done < <(find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' | sort -r)
  return 1
}

if ! latest=$(select_latest_completed_backup); then
  printf 'DATABASE_RESTORE=FAIL\nREASON=no-verified-completed-backup\n' >&2
  exit 1
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$evidence_root"
work=$(mktemp -d "${evidence_root}/.work-${stamp}.XXXXXX")
final="${evidence_root}/${stamp}"
container="codestra-database-restore-${stamp//[^0-9A-Za-z]/}"
volume="${container}-data"
started=$(date +%s)
restore_complete=false

cleanup_runtime_resources() {
  if docker inspect "$container" >/dev/null 2>&1; then
    docker rm -f "$container" >/dev/null
  fi
  if docker volume inspect "$volume" >/dev/null 2>&1; then
    docker volume rm "$volume" >/dev/null
  fi
}

cleanup() {
  cleanup_runtime_resources >/dev/null 2>&1 || true
  find "$work" -xdev -type f -delete 2>/dev/null || true
  find "$work" -xdev -depth -type d -empty -delete 2>/dev/null || true
  if [[ "$restore_complete" != true && -d "$final" ]]; then
    find "$final" -xdev -depth -delete 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'printf "DATABASE_RESTORE=FAIL\n" >&2' ERR
install -d -m 0700 "$final"

mapfile -t encrypted_files < <(find "$latest" -maxdepth 1 -name 'databases-*.tar.gz.gpg' -type f)
[[ "${#encrypted_files[@]}" -eq 1 ]]
encrypted=${encrypted_files[0]}
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
for _ in $(seq 1 60); do
  docker run --rm --network "container:$container" "$image" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1 && break
  sleep 1
done
docker run --rm --network "container:$container" "$image" pg_isready -h 127.0.0.1 -U postgres >/dev/null

count=$(docker run --rm --network "container:$container" -v "$work:/restore:ro" "$image" sh -c '
  set -eu
  count=0
  for archive in /restore/*.dump; do
    name=$(basename "$archive" .dump | tr -c "a-zA-Z0-9_" "_")
    createdb -h 127.0.0.1 -U postgres "$name"
    pg_restore -h 127.0.0.1 -U postgres --no-owner --no-privileges --exit-on-error -d "$name" "$archive"
    test "$(psql -X -h 127.0.0.1 -U postgres -d "$name" -At -v ON_ERROR_STOP=1 -c "select 1")" = 1
    count=$((count+1))
  done
  printf "%s\n" "$count"
')
test "$count" -eq 10

# Remove and positively verify disposable resources before recording a PASS.
cleanup_runtime_resources
if docker inspect "$container" >/dev/null 2>&1; then
  printf 'DATABASE_RESTORE=FAIL\nREASON=residual-container\n' >&2
  exit 1
fi
if docker volume inspect "$volume" >/dev/null 2>&1; then
  printf 'DATABASE_RESTORE=FAIL\nREASON=residual-volume\n' >&2
  exit 1
fi

rto=$(( $(date +%s) - started ))
cat > "$final/RESTORE-RESULT.txt" <<EOF
DATABASE_RESTORE=PASS
RESTORE_TIMESTAMP=${stamp}
BACKUP_TIMESTAMP=$(sed -n 's/^BACKUP_TIMESTAMP=//p' "$latest/STATUS.txt")
POSTGRES_DATABASE_COUNT=${count}
SQLITE_DATABASE_COUNT=1
RESTORE_RTO_SECONDS=${rto}
RESTORE_PUBLIC_PORTS=0
RESTORE_RESIDUAL_RESOURCES=0
EOF
sha256sum "$final/RESTORE-RESULT.txt" > "$final/SHA256SUMS"
restore_complete=true
printf '%s\n' "$final"
