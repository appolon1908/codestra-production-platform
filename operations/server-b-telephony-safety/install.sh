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

payload=$base/codestra-server-b-telephony-safety
sudoers_source=$base/codestra-server-b-telephony-safety.sudoers
sshd_source=$base/sshd-match.conf
python3 -m py_compile "$payload"
visudo -cf "$sudoers_source" >/dev/null
sshd -t -f /etc/ssh/sshd_config

stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=/root/codestra-server-b-telephony-safety-backup-$stamp
install -d -o root -g root -m 0700 "$backup"
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

stage=$(mktemp -d /root/codestra-server-b-telephony-safety-stage.XXXXXX)
trap 'chmod -R u+rwX "$stage" 2>/dev/null || true; rm -rf -- "$stage"' EXIT
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

install -d -o root -g root -m 0755 /etc/codestra/server-b-telephony-safety
install -o root -g root -m 0750 "$stage/operator" /usr/local/sbin/.codestra-server-b-telephony-safety.new
install -o root -g root -m 0440 "$stage/sudoers" /etc/sudoers.d/.codestra-server-b-telephony-safety.new
install -o root -g root -m 0644 "$stage/sshd" /etc/ssh/sshd_config.d/.61-codestra-server-b-telephony-safety.conf.new
install -o root -g root -m 0444 "$stage/REVISION" /etc/codestra/server-b-telephony-safety/.REVISION.new
install -o root -g root -m 0444 "$stage/SHA256SUMS" /etc/codestra/server-b-telephony-safety/.SHA256SUMS.new
mv -f /usr/local/sbin/.codestra-server-b-telephony-safety.new /usr/local/sbin/codestra-server-b-telephony-safety
mv -f /etc/sudoers.d/.codestra-server-b-telephony-safety.new /etc/sudoers.d/codestra-server-b-telephony-safety
mv -f /etc/ssh/sshd_config.d/.61-codestra-server-b-telephony-safety.conf.new /etc/ssh/sshd_config.d/61-codestra-server-b-telephony-safety.conf
mv -f /etc/codestra/server-b-telephony-safety/.REVISION.new /etc/codestra/server-b-telephony-safety/REVISION
mv -f /etc/codestra/server-b-telephony-safety/.SHA256SUMS.new /etc/codestra/server-b-telephony-safety/SHA256SUMS
visudo -cf /etc/sudoers >/dev/null
sshd -t
sha256sum -c /etc/codestra/server-b-telephony-safety/SHA256SUMS >/dev/null
[[ $(cat /etc/codestra/server-b-telephony-safety/REVISION) == "$revision" ]] || die INSTALLED_REVISION_MISMATCH
echo "INSTALL=PASS"
echo "REVISION=$revision"
echo "BACKUP=$backup"
