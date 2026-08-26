#!/usr/bin/env bash
set -euo pipefail
umask 077

wal_name="${1:?WAL name required}"
destination="${2:?restore destination required}"
[[ "$wal_name" =~ ^([0-9A-F]{24}(\.[0-9A-F]{8}\.backup)?|[0-9A-F]{8}\.history)$ ]]
[[ "$destination" != *..* ]]
artifact="/recovery-archive/$wal_name.gpg"
checksum="$artifact.sha256"
[[ -f "$artifact" && -f "$checksum" ]]
(cd /recovery-archive && sha256sum -c "$(basename "$checksum")" >/dev/null)
temporary="${destination}.partial"
trap 'find "$temporary" -delete 2>/dev/null || true' EXIT
gpg --homedir /run/recovery-secrets/gpg --batch --quiet --decrypt \
  --output "$temporary" "$artifact"
mv "$temporary" "$destination"
