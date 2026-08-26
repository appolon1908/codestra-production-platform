#!/usr/bin/env bash
set -euo pipefail
umask 077

test "$(id -u)" -eq 0
authority="${CODESTRA_SHARED_POSTGRES_AUTHORITY:-/etc/codestra/secrets/shared-postgresql}"
state="${CODESTRA_SHARED_POSTGRES_STATE:-/var/lib/codestra-shared-postgresql}"
lock_path="${CODESTRA_SHARED_POSTGRES_RESTIC_LOCK:-/run/lock/codestra-shared-postgresql-restic.lock}"
[[ -d "$authority" && ! -L "$authority" ]]
install -d -m 0700 "$state"
install -d -m 0755 "$(dirname "$lock_path")"

safe_root_secret() {
  local path="$1" mode owner
  [[ -f "$path" && ! -L "$path" && -s "$path" ]] || return 1
  mode="$(stat -c '%a' "$path")"; owner="$(stat -c '%u' "$path")"
  [[ "$owner" == 0 && $((8#$mode & 077)) -eq 0 ]]
}

safe_root_secret "$authority/restic-password"
RESTIC_REPOSITORY="$(<"$authority/restic-repository")"
wal_retention_days="$(<"$authority/wal-retention-days")"
[[ -n "$RESTIC_REPOSITORY" && "$wal_retention_days" =~ ^[1-9][0-9]*$ ]]
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE="$authority/restic-password"
export RESTIC_CACHE_DIR="${CODESTRA_SHARED_POSTGRES_RESTIC_CACHE:-/opt/codestra/backups/postgresql-shared/.restic-cache}"
if [[ -f "$authority/object-access-key-id" ]]; then AWS_ACCESS_KEY_ID="$(<"$authority/object-access-key-id")"; export AWS_ACCESS_KEY_ID; fi
if [[ -f "$authority/object-secret-access-key" ]]; then AWS_SECRET_ACCESS_KEY="$(<"$authority/object-secret-access-key")"; export AWS_SECRET_ACCESS_KEY; fi
if [[ -f "$authority/object-region" ]]; then AWS_DEFAULT_REGION="$(<"$authority/object-region")"; export AWS_DEFAULT_REGION; fi

failures=0
[[ ! -f "$state/restic_maintenance_failures_total" ]] || failures="$(<"$state/restic_maintenance_failures_total")"
[[ "$failures" =~ ^[0-9]+$ ]] || failures=0
on_error() {
  trap - ERR
  failures=$((failures + 1))
  printf '%s\n' "$failures" >"$state/restic_maintenance_failures_total"
  exit 1
}
trap on_error ERR

exec 9>"$lock_path"
flock -w 300 9
restic check --read-data-subset="${RESTIC_CHECK_SUBSET:-1/20}"
restic forget --quiet --tag shared-postgresql-base --keep-weekly 8 --keep-monthly 12
restic forget --quiet --tag shared-postgresql-wal --keep-within "${wal_retention_days}d"
restic prune --max-unused "${RESTIC_MAX_UNUSED:-5%}"
restic check --read-data-subset="${RESTIC_CHECK_SUBSET:-1/20}"

used_bytes="$(restic stats --mode raw-data --json | python3 -c 'import json,sys; value=json.load(sys.stdin).get("total_size", -1); print(value)')"
[[ "$used_bytes" =~ ^[0-9]+$ ]]
capacity_bytes=0
if [[ -f "$authority/restic-capacity-bytes" ]]; then
  capacity_bytes="$(<"$authority/restic-capacity-bytes")"
  [[ "$capacity_bytes" =~ ^[1-9][0-9]*$ && "$used_bytes" -le "$capacity_bytes" ]]
fi
printf '%s\n' "$used_bytes" >"$state/restic_repository_used_bytes"
printf '%s\n' "$capacity_bytes" >"$state/restic_repository_capacity_bytes"
printf '%s\n' "$(date +%s)" >"$state/restic_maintenance_last_success"
printf '%s\n' "$failures" >"$state/restic_maintenance_failures_total"
trap - ERR
