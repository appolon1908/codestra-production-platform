#!/usr/bin/env bash
set -euo pipefail
ARCHIVE=${1:?encrypted archive required}
DEST=${2:?isolated destination required}
[ ! -e "$DEST" ] || { echo 'destination must not exist' >&2; exit 2; }
mkdir -m 0700 "$DEST"
expected=$(awk 'NR==1{print $1}' "$ARCHIVE.sha256")
actual=$(sha256sum "$ARCHIVE" | awk '{print $1}')
[ -n "$expected" ] && [ "$expected" = "$actual" ]
gpg --homedir /etc/codestra/backup-gpg --batch --decrypt "$ARCHIVE" | tar --xattrs --acls --numeric-owner -C "$DEST" -xf -
CA="$DEST/var/lib/caddy/.local/share/caddy/pki/authorities/local"
if [ -f "$CA/root.crt" ] && [ -f "$CA/root.key" ]; then
  cert=$(openssl x509 -in "$CA/root.crt" -pubkey -noout | openssl sha256)
  key=$(openssl pkey -in "$CA/root.key" -pubout | openssl sha256)
  [ "$cert" = "$key" ]
fi
find "$DEST/var/lib/caddy" -type f -perm /0077 -print -quit | grep -q . && { echo unsafe_permissions >&2; exit 3; } || true
echo CADDY_STATE_RESTORE=PASS
