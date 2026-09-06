#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo ERROR=ROOT_AND_BACKUP_REQUIRED >&2; exit 64; }
backup=$1
[[ $backup =~ ^/root/codestra-server-b-telephony-safety-backup-[0-9]{8}T[0-9]{6}Z$ && -d $backup && ! -L $backup ]] || { echo ERROR=INVALID_BACKUP >&2; exit 64; }
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
