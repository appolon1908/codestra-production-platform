#!/usr/bin/env bash
set -euo pipefail
umask 077

stage="${CODESTRA_SHARED_WAL_STAGE:-/var/spool/codestra/postgresql-shared/wal}"
state="${CODESTRA_SHARED_POSTGRES_STATE:-/var/lib/codestra-shared-postgresql}"
retention_days="${1:?retention days required}"
[[ "$retention_days" =~ ^[1-9][0-9]*$ && -d "$stage" && ! -L "$stage" ]]
mkdir -p "$state"; chmod 0700 "$state"
[[ ! -e "$stage/.recovery-hold" ]] || exit 0
deleted=0; failed=0
[[ ! -f "$state/wal_cleanup_deleted_total" ]] || deleted="$(<"$state/wal_cleanup_deleted_total")"
[[ ! -f "$state/wal_cleanup_failures_total" ]] || failed="$(<"$state/wal_cleanup_failures_total")"
while IFS= read -r -d '' marker; do
  source_path="${marker%.offhost}"
  if [[ "$source_path" != "$stage"/[0-9A-F]* || ! -f "$source_path" || -L "$source_path" || -L "$marker" ]] \
    || ! grep -qx 'STATUS=PASS' "$marker" \
    || ! grep -qx 'EVIDENCE_TYPE=WAL_OFFHOST' "$marker"; then
    failed=$((failed + 1)); continue
  fi
  find "$source_path" "$marker" -delete
  deleted=$((deleted + 1))
# Retention is measured from WAL generation (the staged source mtime), not
# from completion of a delayed off-host upload. A marker may be recent after
# an offload backlog, but it only authorizes deletion; it must not restart the
# local retention clock.
done < <(find "$stage" -maxdepth 1 -type f ! -name '*.offhost' -mtime "+$retention_days" -print0 |
  while IFS= read -r -d '' source_path; do
    marker="${source_path}.offhost"
    [[ -f "$marker" && ! -L "$marker" ]] && printf '%s\0' "$marker"
  done)
printf '%s\n' "$deleted" >"$state/wal_cleanup_deleted_total"
printf '%s\n' "$failed" >"$state/wal_cleanup_failures_total"
