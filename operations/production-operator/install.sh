#!/bin/bash
set -euo pipefail
umask 077

die() { printf 'INSTALL_RESULT=FAIL\nREASON=%s\n' "$1" >&2; exit 1; }
test "$(id -u)" -eq 0 || die 'root is required'
test "$#" -eq 4 || die 'expected SHA DIGEST CHANGE_ID MAINTENANCE_DATE'
sha=$1 digest=$2 change_id=$3 maintenance_date=$4
[[ $sha =~ ^[0-9a-f]{40}$ ]] || die 'invalid SHA'
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || die 'invalid digest'
[[ $change_id =~ ^CHG-[0-9]{8}-CODESTRA-PRODUCTION-ACTIVATION-[0-9]{2}$ ]] || die 'invalid change ID'
[[ $maintenance_date =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}$ ]] || die 'invalid maintenance date'

source_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
test ! -L "$source_dir/codestra-production-operator.py" || die 'operator source may not be a symlink'
test ! -L "$source_dir/operator.pub" || die 'public key may not be a symlink'
/usr/bin/ssh-keygen -l -f "$source_dir/operator.pub" -E sha256 >/dev/null || die 'invalid public key'

/usr/bin/install -d -o root -g root -m 0755 /etc/codestra/production-operator
/usr/bin/install -d -o root -g root -m 0755 /var/log/codestra
/usr/bin/install -d -o root -g root -m 0750 /var/lib/codestra/production-operator/evidence
/usr/bin/install -o root -g root -m 0755 "$source_dir/codestra-production-operator.py" /usr/local/sbin/codestra-production-operator

/usr/bin/python3 - "$sha" "$digest" "$change_id" "$maintenance_date" <<'PY'
import json, os, sys, tempfile
target = "/etc/codestra/production-operator/release.json"
data = dict(zip(("protected_sha", "image_digest", "change_id", "maintenance_date"), sys.argv[1:]))
fd, temporary = tempfile.mkstemp(dir=os.path.dirname(target), prefix="release.")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(data, handle, sort_keys=True)
    handle.write("\n")
os.chmod(temporary, 0o600)
os.replace(temporary, target)
PY
/usr/bin/chown root:root /etc/codestra/production-operator/release.json

sudoers=/etc/sudoers.d/codestra-production-operator
printf '%s\n' \
  'Defaults!/usr/local/sbin/codestra-production-operator env_keep += "SSH_ORIGINAL_COMMAND"' \
  'codestra-admin ALL=(root) NOPASSWD: /usr/local/sbin/codestra-production-operator forced' \
  > "$sudoers"
/usr/bin/chown root:root "$sudoers"
/usr/bin/chmod 0440 "$sudoers"
/usr/sbin/visudo -cf "$sudoers" >/dev/null || die 'sudoers validation failed'

home=$(/usr/bin/getent passwd codestra-admin | /usr/bin/cut -d: -f6)
if test -z "$home" || test ! -d "$home"; then
  die 'codestra-admin home is unavailable'
fi
/usr/bin/install -d -o codestra-admin -g codestra-admin -m 0700 "$home/.ssh"
key=$(/usr/bin/cut -d' ' -f1,2 "$source_dir/operator.pub")
entry="restrict,command=\"sudo -n /usr/local/sbin/codestra-production-operator forced\" $key codestra-production-operator"
authorized="$home/.ssh/authorized_keys"
test ! -L "$home/.ssh" || die 'SSH directory may not be a symlink'
test ! -L "$authorized" || die 'authorized_keys may not be a symlink'
test ! -e "$authorized.new" || die 'temporary authorized_keys path already exists'
/usr/bin/touch "$authorized"
/usr/bin/chown codestra-admin:codestra-admin "$authorized"
/usr/bin/chmod 0600 "$authorized"
/usr/bin/grep -Fv ' codestra-production-operator' "$authorized" > "$authorized.new" || true
printf '%s\n' "$entry" >> "$authorized.new"
/usr/bin/chown codestra-admin:codestra-admin "$authorized.new"
/usr/bin/chmod 0600 "$authorized.new"
/usr/bin/mv "$authorized.new" "$authorized"

/usr/local/sbin/codestra-production-operator status "$sha" "$digest" "$change_id" "$maintenance_date" >/dev/null
printf '%s\n' 'INSTALL_RESULT=PASS' 'FORCED_COMMAND_SSH=PASS' 'RESTRICTED_SUDO_POLICY=PASS'
