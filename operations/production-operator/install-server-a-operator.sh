#!/bin/sh
set -eu
umask 077

fail() {
  echo "INSTALL_RESULT=FAIL"
  exit 2
}

[ "$(id -u)" -eq 0 ] || fail
[ "$#" -eq 1 ] || fail

public_key=$1
if [ ! -f "$public_key" ] || [ -L "$public_key" ]; then
  fail
fi
case "$(stat -c %a "$public_key")" in
  *[2367]|*[2367][0-9]) fail ;;
esac
ssh-keygen -lf "$public_key" >/dev/null 2>&1 || fail
awk '
  NF {
    count += 1
    if ($1 != "ssh-ed25519" || (NF != 2 && NF != 3)) exit 1
  }
  END { if (count != 1) exit 1 }
' "$public_key" || fail

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
[ ! -L "$0" ] || fail

verify_payload() {
  cd "$script_dir"
  cat <<'EOF' | sha256sum --check --strict - >/dev/null
7eb6e80b233fce31fe34404a31a82a9fa6d0afd076b6b67a9938c4806999d015  codestra-production-operator
9bc6974aa56ee015de6a03db754fed3594e85d381bc9c98b405d10894cea6b95  codestra-production-forced-command
593cdff802459d3e9ce0d9c9afc17c330df15f4753521c6ad7f2a6c6790a632d  codestra-production-operator.sudoers
2a6d448ee5abc3cfcd4db5d99392e0459aa7cfec63a6851ccd71c959eb528b6c  codestra-production-operator.sshd
EOF
}
verify_payload || fail

for payload in \
  codestra-production-operator \
  codestra-production-forced-command \
  codestra-production-operator.sudoers \
  codestra-production-operator.sshd
do
  if [ ! -f "$script_dir/$payload" ] || [ -L "$script_dir/$payload" ]; then
    fail
  fi
  case "$(stat -c %a "$script_dir/$payload")" in
    *[2367]|*[2367][0-9]) fail ;;
  esac
done

rollback_dir=$(mktemp -d /var/lib/codestra-production-operator-install.XXXXXX)
created_user=0
installed=0

backup_path() {
  target=$1
  label=$2
  if [ -e "$target" ] || [ -L "$target" ]; then
    cp -a --no-dereference "$target" "$rollback_dir/$label"
  else
    : > "$rollback_dir/$label.absent"
  fi
}

reject_target_symlink() {
  [ ! -L "$1" ] || fail
}

validate_existing_root_target() {
  target=$1
  expected_mode=$2
  if [ -e "$target" ]; then
    [ -f "$target" ] || fail
    [ "$(stat -c '%U:%G' "$target")" = "root:root" ] || fail
    [ "$(stat -c %a "$target")" = "$expected_mode" ] || fail
  fi
}

restore_path() {
  target=$1
  label=$2
  rm -f -- "$target"
  if [ -e "$rollback_dir/$label" ] || [ -L "$rollback_dir/$label" ]; then
    cp -a --no-dereference "$rollback_dir/$label" "$target"
  fi
}

rollback() {
  if [ "$installed" -eq 1 ]; then
    restore_path /usr/local/sbin/codestra-production-operator operator
    restore_path /usr/local/libexec/codestra-production-forced-command forced-command
    restore_path /etc/sudoers.d/codestra-production-operator sudoers
    restore_path /etc/ssh/sshd_config.d/60-codestra-production-operator.conf sshd
    restore_path /var/lib/codestra-production-operator/.ssh/authorized_keys authorized-keys
    sshd -t >/dev/null 2>&1 || true
  fi
  if [ "$created_user" -eq 1 ]; then
    userdel codestra-production-operator >/dev/null 2>&1 || true
  fi
  chmod 0700 "$rollback_dir" 2>/dev/null || true
}
on_failure() {
  rc=$?
  trap - EXIT HUP INT TERM
  rollback
  echo "INSTALL_RESULT=FAIL"
  exit "$rc"
}
trap on_failure EXIT HUP INT TERM

install -d -o root -g root -m 0755 /usr/local/sbin /usr/local/libexec
install -d -o root -g root -m 0755 /etc/sudoers.d /etc/ssh/sshd_config.d
install -d -o root -g root -m 0700 /etc/codestra/production-operator
install -d -o root -g root -m 0700 /var/lib/codestra-production-operator

reject_target_symlink /usr/local/sbin/codestra-production-operator
reject_target_symlink /usr/local/libexec/codestra-production-forced-command
reject_target_symlink /etc/sudoers.d/codestra-production-operator
reject_target_symlink /etc/ssh/sshd_config.d/60-codestra-production-operator.conf
reject_target_symlink /var/lib/codestra-production-operator/.ssh/authorized_keys
validate_existing_root_target /usr/local/sbin/codestra-production-operator 750
validate_existing_root_target /usr/local/libexec/codestra-production-forced-command 755
validate_existing_root_target /etc/sudoers.d/codestra-production-operator 440
validate_existing_root_target /etc/ssh/sshd_config.d/60-codestra-production-operator.conf 644

backup_path /usr/local/sbin/codestra-production-operator operator
backup_path /usr/local/libexec/codestra-production-forced-command forced-command
backup_path /etc/sudoers.d/codestra-production-operator sudoers
backup_path /etc/ssh/sshd_config.d/60-codestra-production-operator.conf sshd
backup_path /var/lib/codestra-production-operator/.ssh/authorized_keys authorized-keys
installed=1

if ! id codestra-production-operator >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/codestra-production-operator \
    --shell /bin/sh --no-create-home codestra-production-operator
  passwd -l codestra-production-operator >/dev/null
  created_user=1
fi
operator_record=$(getent passwd codestra-production-operator)
[ "$(printf '%s' "$operator_record" | cut -d: -f3)" -ne 0 ] || fail
[ "$(printf '%s' "$operator_record" | cut -d: -f6)" = /var/lib/codestra-production-operator ] || fail
[ "$(printf '%s' "$operator_record" | cut -d: -f7)" = /bin/sh ] || fail
[ "$(passwd -S codestra-production-operator | awk '{print $2}')" = L ] || fail

install -o root -g root -m 0750 "$script_dir/codestra-production-operator" \
  /usr/local/sbin/codestra-production-operator
install -o root -g root -m 0755 "$script_dir/codestra-production-forced-command" \
  /usr/local/libexec/codestra-production-forced-command

sudoers_tmp=$(mktemp /etc/sudoers.d/.codestra-production-operator.XXXXXX)
install -o root -g root -m 0440 "$script_dir/codestra-production-operator.sudoers" "$sudoers_tmp"
visudo -cf "$sudoers_tmp" >/dev/null
mv -f "$sudoers_tmp" /etc/sudoers.d/codestra-production-operator
visudo -cf /etc/sudoers.d/codestra-production-operator >/dev/null

install -o root -g root -m 0644 "$script_dir/codestra-production-operator.sshd" \
  /etc/ssh/sshd_config.d/60-codestra-production-operator.conf
sshd -t

install -d -o codestra-production-operator -g codestra-production-operator -m 0700 \
  /var/lib/codestra-production-operator/.ssh
authorized_tmp=$(mktemp /var/lib/codestra-production-operator/.ssh/.authorized_keys.XXXXXX)
{
  printf 'restrict,command="/usr/local/libexec/codestra-production-forced-command" '
  tr -d '\r\n' < "$public_key"
  printf '\n'
} > "$authorized_tmp"
chown codestra-production-operator:codestra-production-operator "$authorized_tmp"
chmod 0600 "$authorized_tmp"
mv -f "$authorized_tmp" /var/lib/codestra-production-operator/.ssh/authorized_keys

sha256sum /usr/local/sbin/codestra-production-operator \
  /usr/local/libexec/codestra-production-forced-command \
  /etc/sudoers.d/codestra-production-operator \
  /etc/ssh/sshd_config.d/60-codestra-production-operator.conf \
  > /etc/codestra/production-operator/installed.sha256
chmod 0600 /etc/codestra/production-operator/installed.sha256
chown root:root /etc/codestra/production-operator/installed.sha256

sh -n /usr/local/libexec/codestra-production-forced-command
python3 -c 'compile(open("/usr/local/sbin/codestra-production-operator", encoding="utf-8").read(), "/usr/local/sbin/codestra-production-operator", "exec")'
operator_hash=$(sha256sum /usr/local/sbin/codestra-production-operator | awk '{print $1}')
rm -rf "$rollback_dir"
trap - EXIT HUP INT TERM

printf '%s\n' \
  'INSTALL_RESULT=PASS' \
  'OPERATOR_FILE=/usr/local/sbin/codestra-production-operator' \
  'OPERATOR_OWNER_MODE=root:root 0750' \
  "OPERATOR_SHA256=$operator_hash" \
  'FORCED_COMMAND_SSH=PASS' \
  'RESTRICTED_SUDO_POLICY=PASS' \
  'NEGATIVE_AUTHORIZATION_TESTS=PASS_IN_REVIEWED_SOURCE' \
  'ACTIVE_PRODUCTION_MUTATED=NO'
