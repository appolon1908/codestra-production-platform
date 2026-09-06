#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo ERROR=ROOT_AND_BACKUP_REQUIRED >&2; exit 64; }
lock_parent=/root/vicidial-sync-remediation
lock_root=$lock_parent/.locks
for directory in "$lock_parent" "$lock_root"; do
  if [[ ! -e $directory ]]; then install -d -o root -g root -m 0700 "$directory"; fi
  [[ -d $directory && ! -L $directory && $(stat -c '%U:%G %a' "$directory") == 'root:root 700' ]] || { echo ERROR=UNSAFE_INSTALLER_LOCK_ROOT >&2; exit 64; }
done
lock_path=$lock_root/server-b-telephony-safety-install.lock
if [[ ! -e $lock_path ]]; then
  (umask 077; set -o noclobber; : >"$lock_path") 2>/dev/null || true
fi
[[ -f $lock_path && ! -L $lock_path && $(stat -c '%U:%G %a' "$lock_path") == 'root:root 600' ]] || { echo ERROR=UNSAFE_INSTALLER_LOCK >&2; exit 64; }
exec {installer_lock}<>"$lock_path"
flock -n "$installer_lock" || { echo ERROR=INSTALLER_ALREADY_RUNNING >&2; exit 64; }
backup=$1
[[ $backup =~ ^/root/codestra-server-b-telephony-safety-backup-[A-Za-z0-9]{12}$ && -d $backup && ! -L $backup ]] || { echo ERROR=INVALID_BACKUP >&2; exit 64; }
[[ $(stat -c '%U:%G %a' "$backup") == 'root:root 700' ]] || { echo ERROR=UNSAFE_BACKUP_METADATA >&2; exit 64; }
[[ -f $backup/COMPLETE && ! -L $backup/COMPLETE && $(cat "$backup/COMPLETE") == 'BACKUP_FORMAT=server-b-telephony-safety-v2' ]] || { echo ERROR=INCOMPLETE_BACKUP >&2; exit 64; }
[[ -f $backup/BACKUP-SHA256SUMS && ! -L $backup/BACKUP-SHA256SUMS ]] || { echo ERROR=BACKUP_MANIFEST_MISSING >&2; exit 64; }
(cd "$backup" && sha256sum -c BACKUP-SHA256SUMS >/dev/null) || { echo ERROR=BACKUP_CHECKSUM_MISMATCH >&2; exit 64; }
[[ -f $backup/state.tsv && ! -L $backup/state.tsv ]] || { echo ERROR=BACKUP_STATE_MISSING >&2; exit 64; }
while IFS=$'\t' read -r state name path; do
  case "$name:$path" in
    operator:/usr/local/sbin/codestra-server-b-telephony-safety) mode=0750 ;;
    sudoers:/etc/sudoers.d/codestra-server-b-telephony-safety) mode=0440 ;;
    sshd:/etc/ssh/sshd_config.d/61-codestra-server-b-telephony-safety.conf) mode=0644 ;;
    REVISION:/etc/codestra/server-b-telephony-safety/REVISION|SHA256SUMS:/etc/codestra/server-b-telephony-safety/SHA256SUMS) mode=0444 ;;
    *) echo ERROR=UNSAFE_BACKUP_STATE >&2; exit 64 ;;
  esac
  case $state in
    PRESENT)
      [[ -f $backup/$name && ! -L $backup/$name ]] || { echo ERROR=BACKUP_FILE_MISSING >&2; exit 64; }
      install -o root -g root -m "$mode" "$backup/$name" "$path"
      ;;
    ABSENT) rm -f -- "$path" ;;
    *) echo ERROR=INVALID_BACKUP_STATE >&2; exit 64 ;;
  esac
done <"$backup/state.tsv"
visudo -cf /etc/sudoers >/dev/null
sshd -t
echo ROLLBACK=PASS
