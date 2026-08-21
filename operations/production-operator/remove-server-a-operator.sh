#!/bin/sh
set -eu
umask 077

[ "$(id -u)" -eq 0 ] || exit 2
[ "$#" -eq 0 ] || exit 2

archive_dir=/var/lib/codestra-production-operator/removal
install -d -o root -g root -m 0700 "$archive_dir"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
archive="$archive_dir/$stamp.tar"
tar -cf "$archive" --ignore-failed-read \
  /usr/local/sbin/codestra-production-operator \
  /usr/local/libexec/codestra-production-forced-command \
  /etc/sudoers.d/codestra-production-operator \
  /etc/ssh/sshd_config.d/60-codestra-production-operator.conf \
  /etc/codestra/production-operator/release.json \
  /etc/codestra/production-operator/maintenance-date \
  /var/lib/codestra-production-operator/.ssh/authorized_keys
chmod 0600 "$archive"
sha256sum "$archive" > "$archive.sha256"
chmod 0600 "$archive.sha256"

rm -f /etc/sudoers.d/codestra-production-operator
rm -f /etc/ssh/sshd_config.d/60-codestra-production-operator.conf
rm -f /var/lib/codestra-production-operator/.ssh/authorized_keys
rm -f /etc/codestra/production-operator/release.json
rm -f /etc/codestra/production-operator/maintenance-date
rm -f /usr/local/libexec/codestra-production-forced-command
rm -f /usr/local/sbin/codestra-production-operator
usermod -L codestra-production-operator >/dev/null 2>&1 || true
sshd -t
visudo -cf /etc/sudoers >/dev/null
printf 'REMOVE_RESULT=PASS\nROLLBACK_ARCHIVE=%s\n' "$archive"
