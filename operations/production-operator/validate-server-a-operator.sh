#!/bin/sh
set -eu

[ "$#" -eq 0 ] || exit 2
test "$(stat -c '%U:%G %a' /etc/codestra/production-operator)" = 'root:root 755'
test "$(stat -c '%U:%G %a' /usr/local/sbin/codestra-production-operator)" = 'root:root 750'
test "$(stat -c '%U:%G %a' /usr/local/libexec/codestra-production-forced-command)" = 'root:root 755'
test "$(stat -c '%U:%G %a' /etc/sudoers.d/codestra-production-operator)" = 'root:root 440'
test "$(stat -c '%U:%G %a' /etc/ssh/sshd_config.d/60-codestra-production-operator.conf)" = 'root:root 644'
test "$(stat -c '%U:%G %a' /etc/codestra/production-operator/release.json)" = 'root:root 644'
test "$(stat -c '%U:%G %a' /etc/codestra/production-operator/maintenance-date)" = 'root:root 600'
test "$(stat -c '%U:%G %a' /var/lib/codestra-production-operator)" = \
  'root:codestra-production-operator 710'
test "$(stat -c '%U:%G %a' /var/lib/codestra-production-operator/.ssh)" = \
  'codestra-production-operator:codestra-production-operator 700'
test "$(stat -c '%U:%G %a' /var/lib/codestra-production-operator/.ssh/authorized_keys)" = \
  'codestra-production-operator:codestra-production-operator 600'
sudo -u codestra-production-operator \
  test -r /var/lib/codestra-production-operator/.ssh/authorized_keys
sha256sum --check --strict /etc/codestra/production-operator/installed.sha256 >/dev/null
visudo -cf /etc/sudoers.d/codestra-production-operator >/dev/null
sshd -t
sh -n /usr/local/libexec/codestra-production-forced-command
python3 -c 'compile(open("/usr/local/sbin/codestra-production-operator", encoding="utf-8").read(), "/usr/local/sbin/codestra-production-operator", "exec")'
if grep -Eq 'NOPASSWD:[[:space:]]*ALL|ALL[[:space:]]*=[[:space:]]*\(ALL' \
  /etc/sudoers.d/codestra-production-operator; then
  exit 2
fi
printf 'VALIDATE_RESULT=PASS\n'
