#!/usr/bin/env bash
set -euo pipefail
umask 077

source_path="${1:?WAL source path required}"
wal_name="${2:?WAL name required}"
[[ "$wal_name" =~ ^[0-9A-F]{24}(\.[0-9A-F]{8}\.backup)?$ ]]
[[ "$source_path" != *..* && -f "$source_path" ]]

# This directory is provisioned root:postgres 0770. PostgreSQL receives no
# backup credentials; it can only atomically stage immutable WAL for the
# root-controlled offload worker.
spool="${CODESTRA_SHARED_WAL_STAGE:-/var/spool/codestra/postgresql-shared/wal}"
artifact="$spool/$wal_name"
[[ -d "$spool" && ! -L "$spool" ]]
if [[ ! -s "$artifact" ]]; then
  temporary="$(mktemp "$spool/.${wal_name}.XXXXXX")"
  trap 'find "$temporary" -delete 2>/dev/null || true' EXIT
  install -m 0600 "$source_path" "$temporary"
  sync -d "$temporary"
  mv -n "$temporary" "$artifact"
  sync -d "$spool"
fi
test -s "$artifact"
