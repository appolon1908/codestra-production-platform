#!/usr/bin/env bash
set -euo pipefail

file="${1:?approved change file required}"
[[ -f "$file" ]]
# shellcheck disable=SC1090
source "$file"

required=(SHARED_CHANGE_ID SHARED_CHANGE_STATUS SHARED_ACCOUNTABLE_OWNER
  SHARED_RECOVERY_OWNER SHARED_ROLLBACK_OWNER SHARED_RESTART_START
  SHARED_RESTART_END SHARED_TIMEZONE SHARED_RPO_SECONDS SHARED_RTO_SECONDS
  SHARED_WAL_RETENTION_DAYS SHARED_BASE_BACKUP_FREQUENCY
  SHARED_ARCHIVE_DESTINATION SHARED_ARCHIVE_INDEPENDENT_AUTHORITY
  SHARED_HA_DECISION SHARED_BACKUP_EVIDENCE SHARED_OFFHOST_EVIDENCE
  SHARED_RESTORE_EVIDENCE SHARED_ROLLBACK_EVIDENCE)
go=yes
for name in "${required[@]}"; do
  value="${!name:-}"
  if [[ -z "$value" || "$value" == REQUIRED || "$value" == PENDING ]]; then
    go=no
  fi
done
[[ "${SHARED_CHANGE_STATUS:-}" == APPROVED ]] || go=no
[[ "${SHARED_ARCHIVE_INDEPENDENT_AUTHORITY:-}" == YES ]] || go=no
[[ "${SHARED_HA_DECISION:-}" == REQUIRED || "${SHARED_HA_DECISION:-}" == FORMALLY_NOT_REQUIRED ]] || go=no
[[ "${SHARED_RPO_SECONDS:-}" =~ ^[1-9][0-9]*$ ]] || go=no
[[ "${SHARED_RTO_SECONDS:-}" =~ ^[1-9][0-9]*$ ]] || go=no
[[ "${SHARED_WAL_RETENTION_DAYS:-}" =~ ^[1-9][0-9]*$ ]] || go=no
evidence_file() {
  local path="$1" marker="$2" max_age="$3" modified now
  [[ -s "$path" && ! -L "$path" ]] || return 1
  grep -qx "$marker=PASS" "$path" || return 1
  modified="$(stat -c %Y "$path")"
  now="$(date +%s)"
  (( now - modified >= 0 && now - modified <= max_age ))
}
evidence_file "${SHARED_BACKUP_EVIDENCE:-/nonexistent}" BACKUP 3600 || go=no
evidence_file "${SHARED_OFFHOST_EVIDENCE:-/nonexistent}" OFFHOST_BACKUP 3600 || go=no
evidence_file "${SHARED_RESTORE_EVIDENCE:-/nonexistent}" RESTORE_PRECHECK 2592000 || go=no
evidence_file "${SHARED_ROLLBACK_EVIDENCE:-/nonexistent}" ROLLBACK_PRECHECK 2592000 || go=no
start="$(date -d "${SHARED_RESTART_START:-invalid}" +%s 2>/dev/null || true)"
end="$(date -d "${SHARED_RESTART_END:-invalid}" +%s 2>/dev/null || true)"
[[ "$start" =~ ^[0-9]+$ && "$end" =~ ^[0-9]+$ && "$end" -gt "$start" ]] || go=no

echo "CHANGE_AUTHORITY=$([[ "$go" == yes ]] && echo PASS || echo FAIL)"
echo "RPO_RTO_POLICY=$([[ "$go" == yes ]] && echo PASS || echo FAIL)"
echo "RESTART_WINDOW=$([[ "$go" == yes ]] && echo PASS || echo FAIL)"
echo "RECOVERY_EVIDENCE=$([[ "$go" == yes ]] && echo PASS || echo FAIL)"
echo "SHARED_POSTGRES_CUTOVER_GO=$([[ "$go" == yes ]] && echo YES || echo NO)"
[[ "$go" == yes ]]
