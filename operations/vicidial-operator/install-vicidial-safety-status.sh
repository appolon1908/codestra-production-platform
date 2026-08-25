#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 || $# -ne 0 ]]; then
  echo "ERROR=ROOT_WITHOUT_ARGUMENTS_REQUIRED" >&2
  exit 64
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
operator=/usr/local/sbin/codestra-vicidial-operator
core=/usr/local/libexec/codestra-vicidial-operator-core
sudoers=/etc/sudoers.d/codestra-vicidial-safety-status
backup_dir="/root/codestra-vicidial-operator-backup-$(date -u +%Y%m%dT%H%M%SZ)"

test -f "$operator"
test ! -L "$operator"
test "$(stat -c '%U:%G' "$operator")" = root:root
python3 -m py_compile "$script_dir/codestra-vicidial-operator"
visudo -cf "$script_dir/codestra-vicidial-safety-status.sudoers" >/dev/null

install -d -o root -g root -m 0700 "$backup_dir"
install -o root -g root -m 0750 "$operator" "$backup_dir/codestra-vicidial-operator"
tar --create --file "$backup_dir/sudoers.tar" --absolute-names /etc/sudoers /etc/sudoers.d
chmod 0600 "$backup_dir/sudoers.tar"
sha256sum "$backup_dir/codestra-vicidial-operator" "$backup_dir/sudoers.tar" >"$backup_dir/SHA256SUMS"

install -d -o root -g root -m 0755 /usr/local/libexec
if [[ ! -e "$core" ]]; then
  install -o root -g root -m 0750 "$operator" "$core"
fi
test ! -L "$core"
test "$(stat -c '%U:%G %a' "$core")" = "root:root 750"

operator_tmp="$(mktemp /usr/local/sbin/.codestra-vicidial-operator.XXXXXX)"
sudoers_tmp="$(mktemp /etc/sudoers.d/.codestra-vicidial-safety-status.XXXXXX)"
trap 'rm -f "$operator_tmp" "$sudoers_tmp"' EXIT
install -o root -g root -m 0750 "$script_dir/codestra-vicidial-operator" "$operator_tmp"
install -o root -g root -m 0440 "$script_dir/codestra-vicidial-safety-status.sudoers" "$sudoers_tmp"
visudo -cf "$sudoers_tmp" >/dev/null
mv -f "$operator_tmp" "$operator"
mv -f "$sudoers_tmp" "$sudoers"
visudo -cf /etc/sudoers >/dev/null

sudo -n -u codestra-admin sudo -n "$operator" telephony-safety-status >/dev/null
echo "BACKUP_CURRENT_OPERATOR=PASS"
echo "BACKUP_CURRENT_SUDOERS=PASS"
echo "VALIDATION=PASS"
echo "DEPLOYMENT=PASS"
echo "BACKUP_DIR=$backup_dir"
