#!/bin/sh
set -eu
umask 077

fail() {
  echo "INSTALL_RESULT=FAIL"
  exit 2
}

[ "$(id -u)" -eq 0 ] || fail
[ "$#" -eq 6 ] || fail

public_key=$1
protected_sha=$2
[ "$protected_sha" != "01f2676772b11919e1d79cc74d36bc5eeaa682cd" ] || fail
image_digest=$3
change_id=$4
maintenance_date=$5
control_plane_archive_sha256=$6
[ "$(printf '%s' "$protected_sha" | grep -Ec '^[0-9a-f]{40}$')" -eq 1 ] || fail
[ "$(printf '%s' "$image_digest" | grep -Ec '^sha256:[0-9a-f]{64}$')" -eq 1 ] || fail
[ "$(printf '%s' "$change_id" | grep -Ec '^CHG-[0-9]{8}-CODESTRA-PRODUCTION-ACTIVATION-[0-9]{2}$')" -eq 1 ] || fail
[ "$(printf '%s' "$maintenance_date" | grep -Ec '^20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])$')" -eq 1 ] || fail
[ "$(printf '%s' "$control_plane_archive_sha256" | grep -Ec '^[0-9a-f]{64}$')" -eq 1 ] || fail
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
restore_source=$script_dir/../readiness/codestra-isolated-restore-rehearsal.sh
database_manifest_source=$script_dir/../../PRODUCTION-DATABASE-MANIFEST.yaml
database_validator_source=$script_dir/../../tools/validate_production_database_manifest.py

validate_trusted_source() {
  target=$1
  [ -f "$target" ] || fail
  [ ! -L "$target" ] || fail
  [ "$(stat -c '%U:%G' "$target")" = root:root ] || fail
  case "$(stat -c %a "$target")" in
    *[2367]|*[2367][0-9]) fail ;;
  esac
  parent=$(dirname -- "$target")
  while [ "$parent" != / ]; do
    [ -d "$parent" ] || fail
    [ ! -L "$parent" ] || fail
    [ "$(stat -c '%U:%G' "$parent")" = root:root ] || fail
    case "$(stat -c %a "$parent")" in
      *[2367]|*[2367][0-9]) fail ;;
    esac
    parent=$(dirname -- "$parent")
  done
}

verify_payload() {
  cd "$script_dir"
  cat <<'EOF' | sha256sum --check --strict - >/dev/null
0d3e47ffab7f9f64a745b1c631520de6231deda17a52026e1b61c0ab3bc3f64d  codestra-production-operator
80ad3377406d35ee0a5c3ecd827c9320a9e03868c8e01a1626faf2920e1bb8fb  codestra-production-forced-command
aebef8205744a176d26334647f52307b7ded040b5170ca2641fc62cb64417b65  codestra-production-operator.sudoers
2a6d448ee5abc3cfcd4db5d99392e0459aa7cfec63a6851ccd71c959eb528b6c  codestra-production-operator.sshd
dad62a1dcb35fabb97991ad2f0a1079d13d949528daa7bebe0d35d291ec23f67  ../../PRODUCTION-DATABASE-MANIFEST.yaml
c6b3041ead24fb674d982a5787ff4f2d0eabbf0fd9bb45be8bcb695d09647235  ../../tools/validate_production_database_manifest.py
EOF
}
verify_payload || fail
[ ! -L "$restore_source" ] || fail
[ -f "$restore_source" ] || fail
[ "$(sha256sum "$restore_source" | awk '{print $1}')" = 076bc8d33318561fff535f336300d072cd14beb9c756c253a8b1c6a30f3f34f4 ] || fail
[ ! -L "$database_manifest_source" ] || fail
[ -f "$database_manifest_source" ] || fail
[ ! -L "$database_validator_source" ] || fail
[ -f "$database_validator_source" ] || fail
validate_trusted_source "$database_manifest_source"
validate_trusted_source "$database_validator_source"

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
state_dir=/var/lib/codestra-production-operator
state_dir_existed=0
state_dir_metadata_touched=0
state_dir_uid=
state_dir_gid=
state_dir_mode=

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
    restore_path /etc/codestra/production-operator/release.json release-config
    restore_path /etc/codestra/production-operator/maintenance-date maintenance-date
    restore_path /etc/codestra/production-operator/control-plane-archive.sha256 control-plane-archive-checksum
    restore_path /opt/codestra/operations/readiness/codestra-isolated-restore-rehearsal.sh readiness-restore
    restore_path /etc/codestra/production-operator/PRODUCTION-DATABASE-MANIFEST.yaml database-manifest
    restore_path /usr/local/libexec/validate-production-database-manifest database-validator
    sshd -t >/dev/null 2>&1 || true
  fi
  if [ "$state_dir_metadata_touched" -eq 1 ] && [ "$state_dir_existed" -eq 1 ]; then
    chown "$state_dir_uid:$state_dir_gid" "$state_dir" 2>/dev/null || true
    chmod "$state_dir_mode" "$state_dir" 2>/dev/null || true
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

if [ -e "$state_dir" ] || [ -L "$state_dir" ]; then
  if [ ! -d "$state_dir" ] || [ -L "$state_dir" ]; then
    fail
  fi
  state_dir_existed=1
  state_dir_uid=$(stat -c %u "$state_dir")
  state_dir_gid=$(stat -c %g "$state_dir")
  state_dir_mode=$(stat -c %a "$state_dir")
fi

install -d -o root -g root -m 0755 /usr/local/sbin /usr/local/libexec
install -d -o root -g root -m 0755 /etc/sudoers.d /etc/ssh/sshd_config.d
install -d -o root -g root -m 0755 /etc/codestra/production-operator
install -d -o root -g root -m 0755 /opt/codestra/operations/readiness
state_dir_metadata_touched=1
install -d -o root -g codestra-production-operator -m 0710 \
  "$state_dir"

reject_target_symlink /usr/local/sbin/codestra-production-operator
reject_target_symlink /usr/local/libexec/codestra-production-forced-command
reject_target_symlink /etc/sudoers.d/codestra-production-operator
reject_target_symlink /etc/ssh/sshd_config.d/60-codestra-production-operator.conf
reject_target_symlink /var/lib/codestra-production-operator/.ssh/authorized_keys
reject_target_symlink /etc/codestra/production-operator/release.json
reject_target_symlink /etc/codestra/production-operator/maintenance-date
reject_target_symlink /etc/codestra/production-operator/control-plane-archive.sha256
reject_target_symlink /opt/codestra/operations/readiness/codestra-isolated-restore-rehearsal.sh
reject_target_symlink /etc/codestra/production-operator/PRODUCTION-DATABASE-MANIFEST.yaml
reject_target_symlink /usr/local/libexec/validate-production-database-manifest
validate_existing_root_target /usr/local/sbin/codestra-production-operator 750
validate_existing_root_target /usr/local/libexec/codestra-production-forced-command 755
validate_existing_root_target /etc/sudoers.d/codestra-production-operator 440
validate_existing_root_target /etc/ssh/sshd_config.d/60-codestra-production-operator.conf 644
validate_existing_root_target /opt/codestra/operations/readiness/codestra-isolated-restore-rehearsal.sh 755
validate_existing_root_target /etc/codestra/production-operator/PRODUCTION-DATABASE-MANIFEST.yaml 644
validate_existing_root_target /usr/local/libexec/validate-production-database-manifest 755

backup_path /usr/local/sbin/codestra-production-operator operator
backup_path /usr/local/libexec/codestra-production-forced-command forced-command
backup_path /etc/sudoers.d/codestra-production-operator sudoers
backup_path /etc/ssh/sshd_config.d/60-codestra-production-operator.conf sshd
backup_path /var/lib/codestra-production-operator/.ssh/authorized_keys authorized-keys
backup_path /etc/codestra/production-operator/release.json release-config
backup_path /etc/codestra/production-operator/maintenance-date maintenance-date
backup_path /etc/codestra/production-operator/control-plane-archive.sha256 control-plane-archive-checksum
backup_path /opt/codestra/operations/readiness/codestra-isolated-restore-rehearsal.sh readiness-restore
backup_path /etc/codestra/production-operator/PRODUCTION-DATABASE-MANIFEST.yaml database-manifest
backup_path /usr/local/libexec/validate-production-database-manifest database-validator
installed=1

install -o root -g root -m 0750 "$script_dir/codestra-production-operator" \
  /usr/local/sbin/codestra-production-operator
install -o root -g root -m 0755 "$script_dir/codestra-production-forced-command" \
  /usr/local/libexec/codestra-production-forced-command
install -o root -g root -m 0755 "$restore_source" \
  /opt/codestra/operations/readiness/codestra-isolated-restore-rehearsal.sh
install -o root -g root -m 0644 "$database_manifest_source" \
  /etc/codestra/production-operator/PRODUCTION-DATABASE-MANIFEST.yaml
install -o root -g root -m 0755 "$database_validator_source" \
  /usr/local/libexec/validate-production-database-manifest

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

release_tmp=$(mktemp /etc/codestra/production-operator/.release.XXXXXX)
python3 - "$release_tmp" "$protected_sha" "$image_digest" "$change_id" "$maintenance_date" <<'PY'
import json
import sys

target, protected_sha, image_digest, change_id, maintenance_date = sys.argv[1:]
with open(target, "w", encoding="ascii") as stream:
    json.dump({
        "change_id": change_id,
        "image_digest": image_digest,
        "maintenance_date": maintenance_date,
        "protected_sha": protected_sha,
    }, stream, sort_keys=True, separators=(",", ":"))
    stream.write("\n")
PY
chown root:root "$release_tmp"
chmod 0644 "$release_tmp"
mv -f "$release_tmp" /etc/codestra/production-operator/release.json

maintenance_tmp=$(mktemp /etc/codestra/production-operator/.maintenance-date.XXXXXX)
printf '%s\n' "$maintenance_date" > "$maintenance_tmp"
chown root:root "$maintenance_tmp"
chmod 0600 "$maintenance_tmp"
mv -f "$maintenance_tmp" /etc/codestra/production-operator/maintenance-date

control_plane_checksum_tmp=$(mktemp /etc/codestra/production-operator/.control-plane-archive.XXXXXX)
printf '%s\n' "$control_plane_archive_sha256" > "$control_plane_checksum_tmp"
chown root:root "$control_plane_checksum_tmp"
chmod 0644 "$control_plane_checksum_tmp"
mv -f "$control_plane_checksum_tmp" /etc/codestra/production-operator/control-plane-archive.sha256

sha256sum /usr/local/sbin/codestra-production-operator \
  /usr/local/libexec/codestra-production-forced-command \
  /etc/sudoers.d/codestra-production-operator \
  /etc/ssh/sshd_config.d/60-codestra-production-operator.conf \
  /etc/codestra/production-operator/release.json \
  /etc/codestra/production-operator/maintenance-date \
  /etc/codestra/production-operator/control-plane-archive.sha256 \
  /etc/codestra/production-operator/PRODUCTION-DATABASE-MANIFEST.yaml \
  /usr/local/libexec/validate-production-database-manifest \
  /opt/codestra/operations/readiness/codestra-isolated-restore-rehearsal.sh \
  > /etc/codestra/production-operator/installed.sha256
chmod 0600 /etc/codestra/production-operator/installed.sha256
chown root:root /etc/codestra/production-operator/installed.sha256

sh -n /usr/local/libexec/codestra-production-forced-command
bash -n /opt/codestra/operations/readiness/codestra-isolated-restore-rehearsal.sh
python3 -c 'compile(open("/usr/local/sbin/codestra-production-operator", encoding="utf-8").read(), "/usr/local/sbin/codestra-production-operator", "exec")'
python3 -c 'compile(open("/usr/local/libexec/validate-production-database-manifest", encoding="utf-8").read(), "/usr/local/libexec/validate-production-database-manifest", "exec")'
/usr/local/libexec/validate-production-database-manifest \
  /etc/codestra/production-operator/PRODUCTION-DATABASE-MANIFEST.yaml \
  /opt/codestra/evidence/database-certification
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
