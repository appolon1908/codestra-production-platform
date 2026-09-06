#!/usr/bin/env bash
set -euo pipefail

die() { echo "ERROR=$1" >&2; exit 64; }
[[ $EUID -eq 0 && $# -eq 1 ]] || die ROOT_AND_PROTECTED_REVISION_REQUIRED
revision=$1
[[ $revision =~ ^[0-9a-f]{40}$ ]] || die INVALID_PROTECTED_REVISION

base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo=$(git -C "$base" rev-parse --show-toplevel 2>/dev/null) || die GIT_SOURCE_REQUIRED
[[ -z $(git -C "$repo" status --porcelain) ]] || die DIRTY_SOURCE_REJECTED
[[ $(git -C "$repo" rev-parse HEAD) == "$revision" ]] || die REVISION_MISMATCH
git -C "$repo" merge-base --is-ancestor "$revision" origin/release/production-activation || die UNPROTECTED_SOURCE_REJECTED

lock_parent=/root/vicidial-sync-remediation
lock_root=$lock_parent/.locks
for directory in "$lock_parent" "$lock_root"; do
  if [[ ! -e $directory ]]; then install -d -o root -g root -m 0700 "$directory"; fi
  [[ -d $directory && ! -L $directory && $(stat -c '%U:%G %a' "$directory") == 'root:root 700' ]] || die UNSAFE_INSTALLER_LOCK_ROOT
done
lock_path=$lock_root/server-b-telephony-safety-install.lock
if [[ ! -e $lock_path ]]; then
  (umask 077; set -o noclobber; : >"$lock_path") 2>/dev/null || true
fi
[[ -f $lock_path && ! -L $lock_path && $(stat -c '%U:%G %a' "$lock_path") == 'root:root 600' ]] || die UNSAFE_INSTALLER_LOCK
exec {installer_lock}<>"$lock_path"
flock -n "$installer_lock" || die INSTALLER_ALREADY_RUNNING

payload=$base/codestra-server-b-telephony-safety
sudoers_source=$base/codestra-server-b-telephony-safety.sudoers
sshd_source=$base/sshd-match.conf
python3 -m py_compile "$payload"
visudo -cf "$sudoers_source" >/dev/null
sshd -t -f /etc/ssh/sshd_config

backup=$(mktemp -d /root/codestra-server-b-telephony-safety-backup-XXXXXXXXXXXX)
chown root:root "$backup"
chmod 0700 "$backup"
declare -A existing=(
  [operator]=/usr/local/sbin/codestra-server-b-telephony-safety
  [sudoers]=/etc/sudoers.d/codestra-server-b-telephony-safety
  [sshd]=/etc/ssh/sshd_config.d/61-codestra-server-b-telephony-safety.conf
  [REVISION]=/etc/codestra/server-b-telephony-safety/REVISION
  [SHA256SUMS]=/etc/codestra/server-b-telephony-safety/SHA256SUMS
)
for name in operator sudoers sshd REVISION SHA256SUMS; do
  path=${existing[$name]}
  if [[ -e $path ]]; then
    [[ -f $path && ! -L $path ]] || die UNSAFE_EXISTING_TARGET
    cp -a -- "$path" "$backup/$name"
    printf 'PRESENT\t%s\t%s\n' "$name" "$path" >>"$backup/state.tsv"
  else
    printf 'ABSENT\t%s\t%s\n' "$name" "$path" >>"$backup/state.tsv"
  fi
done
chmod 0600 "$backup/state.tsv"
(
  cd "$backup"
  manifest_files=(state.tsv)
  for name in operator sudoers sshd REVISION SHA256SUMS; do
    [[ -f $name ]] && manifest_files+=("$name")
  done
  sha256sum "${manifest_files[@]}" >BACKUP-SHA256SUMS
)
chmod 0600 "$backup/BACKUP-SHA256SUMS"
printf 'BACKUP_FORMAT=server-b-telephony-safety-v2\n' >"$backup/COMPLETE"
chmod 0400 "$backup/COMPLETE"

stage=$(mktemp -d /root/codestra-server-b-telephony-safety-stage.XXXXXX)
install -d -o root -g root -m 0755 /etc/codestra/server-b-telephony-safety
operator_tmp=$(mktemp /usr/local/sbin/.codestra-server-b-telephony-safety.XXXXXXXXXXXX)
sudoers_tmp=$(mktemp /etc/sudoers.d/.codestra-server-b-telephony-safety.XXXXXXXXXXXX)
sshd_tmp=$(mktemp /etc/ssh/sshd_config.d/.61-codestra-server-b-telephony-safety.XXXXXXXXXXXX)
revision_tmp=$(mktemp /etc/codestra/server-b-telephony-safety/.REVISION.XXXXXXXXXXXX)
checksums_tmp=$(mktemp /etc/codestra/server-b-telephony-safety/.SHA256SUMS.XXXXXXXXXXXX)
cleanup() {
  chmod -R u+rwX "$stage" 2>/dev/null || true
  rm -rf -- "$stage"
  rm -f -- "$operator_tmp" "$sudoers_tmp" "$sshd_tmp" "$revision_tmp" "$checksums_tmp"
}
trap cleanup EXIT
install -o root -g root -m 0750 "$payload" "$stage/operator"
install -o root -g root -m 0440 "$sudoers_source" "$stage/sudoers"
install -o root -g root -m 0644 "$sshd_source" "$stage/sshd"
printf '%s\n' "$revision" >"$stage/REVISION"
chmod 0444 "$stage/REVISION"
{
  printf '%s  %s\n' "$(sha256sum "$stage/operator" | awk '{print $1}')" /usr/local/sbin/codestra-server-b-telephony-safety
  printf '%s  %s\n' "$(sha256sum "$stage/sudoers" | awk '{print $1}')" /etc/sudoers.d/codestra-server-b-telephony-safety
  printf '%s  %s\n' "$(sha256sum "$stage/sshd" | awk '{print $1}')" /etc/ssh/sshd_config.d/61-codestra-server-b-telephony-safety.conf
  printf '%s  %s\n' "$(sha256sum "$stage/REVISION" | awk '{print $1}')" /etc/codestra/server-b-telephony-safety/REVISION
} >"$stage/SHA256SUMS"
chmod 0444 "$stage/SHA256SUMS"
visudo -cf "$stage/sudoers" >/dev/null

install -o root -g root -m 0750 "$stage/operator" "$operator_tmp"
install -o root -g root -m 0440 "$stage/sudoers" "$sudoers_tmp"
install -o root -g root -m 0644 "$stage/sshd" "$sshd_tmp"
install -o root -g root -m 0444 "$stage/REVISION" "$revision_tmp"
install -o root -g root -m 0444 "$stage/SHA256SUMS" "$checksums_tmp"
mv -f "$operator_tmp" /usr/local/sbin/codestra-server-b-telephony-safety
mv -f "$sudoers_tmp" /etc/sudoers.d/codestra-server-b-telephony-safety
mv -f "$sshd_tmp" /etc/ssh/sshd_config.d/61-codestra-server-b-telephony-safety.conf
mv -f "$revision_tmp" /etc/codestra/server-b-telephony-safety/REVISION
mv -f "$checksums_tmp" /etc/codestra/server-b-telephony-safety/SHA256SUMS
visudo -cf /etc/sudoers >/dev/null
sshd -t
sha256sum -c /etc/codestra/server-b-telephony-safety/SHA256SUMS >/dev/null
[[ $(cat /etc/codestra/server-b-telephony-safety/REVISION) == "$revision" ]] || die INSTALLED_REVISION_MISMATCH
echo "INSTALL=PASS"
echo "REVISION=$revision"
echo "BACKUP=$backup"
