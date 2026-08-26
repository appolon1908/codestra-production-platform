#!/usr/bin/env bash
set -euo pipefail
umask 077
DEST=${CADDY_BACKUP_DIR:-/var/backups/caddy}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$DEST"
WORK=$(mktemp -d "$DEST/.backup-$STAMP.XXXXXX")
trap 'find "$WORK" -type f -delete 2>/dev/null || true; rmdir "$WORK" 2>/dev/null || true' EXIT
MANIFEST="$WORK/manifest.txt"
find /var/lib/caddy /etc/caddy/private /etc/caddy/secrets /etc/codestra/pki/middleware-private-ingress -xdev -printf '%m %u:%g %s %p\n' | sort >"$MANIFEST"
tar --xattrs --acls --numeric-owner -C / -cf - var/lib/caddy etc/caddy/private etc/caddy/secrets etc/codestra/pki/middleware-private-ingress | gpg --homedir /etc/codestra/backup-gpg --batch --yes --trust-model always --recipient 'Codestra Backup Recipient' --encrypt --output "$WORK/caddy-state.tar.gpg"
sha256sum "$WORK/caddy-state.tar.gpg" >"$WORK/caddy-state.tar.gpg.sha256"
chmod 0600 "$WORK"/*
mv "$WORK/caddy-state.tar.gpg" "$DEST/caddy-state-$STAMP.tar.gpg"
mv "$WORK/caddy-state.tar.gpg.sha256" "$DEST/caddy-state-$STAMP.tar.gpg.sha256"
mv "$MANIFEST" "$DEST/caddy-state-$STAMP.manifest"
ln -sfn "caddy-state-$STAMP.tar.gpg" "$DEST/latest.tar.gpg"
find "$DEST" -maxdepth 1 -type f -name 'caddy-state-*.tar.gpg' -mtime +14 -delete
REMOTE_HOST=${CADDY_BACKUP_REMOTE_HOST:-codestra-vicidial}
REMOTE_DIR=${CADDY_BACKUP_REMOTE_DIR:-/srv/codestra-backups/server-a/caddy}
if timeout 120 ssh -o BatchMode=yes "$REMOTE_HOST" "install -d -m 0700 '$REMOTE_DIR' '$REMOTE_DIR/daily' '$REMOTE_DIR/weekly' '$REMOTE_DIR/monthly'" &&
   timeout 300 scp -q "$DEST/caddy-state-$STAMP.tar.gpg" "$DEST/caddy-state-$STAMP.tar.gpg.sha256" "$DEST/caddy-state-$STAMP.manifest" "$REMOTE_HOST:$REMOTE_DIR/" &&
   timeout 30 ssh -o BatchMode=yes "$REMOTE_HOST" "test -s '$REMOTE_DIR/caddy-state-$STAMP.tar.gpg' &&
     chmod 0600 '$REMOTE_DIR/caddy-state-$STAMP.tar.gpg' '$REMOTE_DIR/caddy-state-$STAMP.tar.gpg.sha256' '$REMOTE_DIR/caddy-state-$STAMP.manifest' &&
     cp -p '$REMOTE_DIR/caddy-state-$STAMP.tar.gpg' '$REMOTE_DIR/daily/' &&
     find '$REMOTE_DIR/daily' -type f -name 'caddy-state-*.tar.gpg' -mtime +14 -delete &&
     find '$REMOTE_DIR/weekly' -type f -name 'caddy-state-*.tar.gpg' -mtime +56 -delete &&
     find '$REMOTE_DIR/monthly' -type f -name 'caddy-state-*.tar.gpg' -mtime +366 -delete"; then
  if [ "$(date -u +%u)" = 7 ]; then ssh -o BatchMode=yes "$REMOTE_HOST" "cp -p '$REMOTE_DIR/caddy-state-$STAMP.tar.gpg' '$REMOTE_DIR/weekly/'"; fi
  if [ "$(date -u +%d)" = 01 ]; then ssh -o BatchMode=yes "$REMOTE_HOST" "cp -p '$REMOTE_DIR/caddy-state-$STAMP.tar.gpg' '$REMOTE_DIR/monthly/'"; fi
  touch "$DEST/offhost-last-success"
  printf '%s\n' "$REMOTE_HOST:$REMOTE_DIR/caddy-state-$STAMP.tar.gpg" >"$DEST/offhost-last-destination"
  echo CADDY_STATE_BACKUP_OFFHOST=PASS
else
  echo CADDY_STATE_BACKUP_OFFHOST=FAIL >&2
  exit 2
fi
echo "BACKUP=$DEST/caddy-state-$STAMP.tar.gpg"
echo CADDY_STATE_BACKUP_LOCAL=PASS
