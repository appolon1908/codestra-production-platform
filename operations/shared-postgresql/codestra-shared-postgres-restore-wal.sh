#!/usr/bin/env bash
set -euo pipefail
umask 077

wal_name="${1:?WAL name required}"
destination="${2:?restore destination required}"
[[ "$wal_name" =~ ^([0-9A-F]{24}(\.[0-9A-F]{8}\.backup)?|[0-9A-F]{8}\.history)$ ]]
[[ "$destination" != *..* ]]
archive="${CODESTRA_SHARED_RECOVERY_ARCHIVE:-/recovery-archive}"
secrets="${CODESTRA_SHARED_RECOVERY_SECRETS:-/run/recovery-secrets}"
[[ -d "$archive" && ! -L "$archive" && -d "$secrets" && ! -L "$secrets" ]]
artifact="$archive/$wal_name.gpg"
checksum="$artifact.sha256"
[[ -f "$artifact" && -f "$checksum" ]]
(cd "$archive" && sha256sum -c "$(basename "$checksum")" >/dev/null)
temporary="${destination}.partial"
runtime_home="$(mktemp -d "${TMPDIR:-/tmp}/codestra-recovery-gpg.XXXXXX")"
cleanup() {
  find "$temporary" -delete 2>/dev/null || true
  find "$runtime_home" -xdev -type f -exec shred -u -- {} + 2>/dev/null || true
  find "$runtime_home" -depth -type d -empty -delete 2>/dev/null || true
}
trap cleanup EXIT
cp -a "$secrets/gpg/." "$runtime_home/"
find "$runtime_home" -xdev -type s -delete
chmod 0700 "$runtime_home"
gpg --homedir "$runtime_home" --batch --quiet --decrypt \
  --output "$temporary" "$artifact"
mv "$temporary" "$destination"
