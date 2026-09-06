#!/usr/bin/env bash
set -euo pipefail
umask 077

approval="${1:?approved change file required}"
declare -A approved=()
block() { printf 'SHARED_POSTGRES_CUTOVER_GO=NO\nBLOCKED_BY=%s\n' "$1"; exit 1; }
safe_file() {
  local path="$1" mode owner
  [[ -f "$path" && ! -L "$path" && -s "$path" ]] || return 1
  mode="$(stat -c '%a' "$path")"; owner="$(stat -c '%u' "$path")"
  [[ "$owner" == "$(id -u)" && $((8#$mode & 077)) -eq 0 ]]
}
safe_file "$approval" || block APPROVAL_FILE_SECURITY
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  [[ "$key" =~ ^SHARED_[A-Z0-9_]+$ && -n "$value" ]] || block APPROVAL_FILE_FORMAT
  approved["$key"]="$value"
done <"$approval"
required=(SHARED_CHANGE_ID SHARED_CHANGE_STATUS SHARED_ACCOUNTABLE_OWNER
  SHARED_RECOVERY_OWNER SHARED_ROLLBACK_OWNER SHARED_RESTART_START
  SHARED_RESTART_END SHARED_TIMEZONE SHARED_RPO_SECONDS SHARED_RTO_SECONDS
  SHARED_WAL_RETENTION_DAYS SHARED_BASE_BACKUP_FREQUENCY
  SHARED_ARCHIVE_DESTINATION SHARED_ARCHIVE_INDEPENDENT_AUTHORITY
  SHARED_HA_DECISION SHARED_BACKUP_EVIDENCE SHARED_OFFHOST_EVIDENCE
  SHARED_RESTORE_EVIDENCE SHARED_ROLLBACK_EVIDENCE)
for key in "${required[@]}"; do
  value="${approved[$key]:-}"
  [[ -n "$value" && "$value" != PENDING ]] || block "MISSING_${key}"
  [[ "$key" == SHARED_HA_DECISION || "$value" != REQUIRED ]] || block "MISSING_${key}"
done
[[ "${approved[SHARED_CHANGE_STATUS]}" == APPROVED ]] || block CHANGE_STATUS
[[ "${approved[SHARED_ARCHIVE_INDEPENDENT_AUTHORITY]}" == YES ]] || block ARCHIVE_INDEPENDENCE
[[ "${approved[SHARED_HA_DECISION]}" == REQUIRED || "${approved[SHARED_HA_DECISION]}" == FORMALLY_NOT_REQUIRED_FOR_THIS_RELEASE ]] || block HA_DECISION
for key in SHARED_RPO_SECONDS SHARED_RTO_SECONDS SHARED_WAL_RETENTION_DAYS; do
  [[ "${approved[$key]}" =~ ^[1-9][0-9]*$ ]] || block "$key"
done
now="$(date +%s)"
start="$(TZ="${approved[SHARED_TIMEZONE]}" date -d "${approved[SHARED_RESTART_START]}" +%s 2>/dev/null || true)"
end="$(TZ="${approved[SHARED_TIMEZONE]}" date -d "${approved[SHARED_RESTART_END]}" +%s 2>/dev/null || true)"
[[ "$start" =~ ^[0-9]+$ && "$end" =~ ^[0-9]+$ && "$end" -gt "$start" ]] || block RESTART_WINDOW_FORMAT
(( now >= start && now <= end )) || block RESTART_WINDOW_INACTIVE

validate_evidence() {
  local path="$1" expected_type="$2" max_age="$3" gate="$4"
  local key value captured_epoch expires_epoch artifact digest actual
  declare -A evidence=()
  safe_file "$path" || block "${gate}_FILE_SECURITY"
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    [[ "$key" =~ ^[A-Z0-9_]+$ && -n "$value" ]] || block "${gate}_FORMAT"
    evidence["$key"]="$value"
  done <"$path"
  for key in CHANGE_ID EVIDENCE_TYPE STATUS CAPTURED_AT SOURCE_HOST ARTIFACT_PATH ARTIFACT_SHA256 EXPIRES_AT; do
    [[ -n "${evidence[$key]:-}" ]] || block "${gate}_MISSING_${key}"
  done
  [[ "${evidence[CHANGE_ID]}" == "${approved[SHARED_CHANGE_ID]}" ]] || block "${gate}_CHANGE_ID"
  [[ "${evidence[EVIDENCE_TYPE]}" == "$expected_type" ]] || block "${gate}_TYPE"
  [[ "${evidence[STATUS]}" == PASS ]] || block "${gate}_STATUS"
  captured_epoch="$(date -d "${evidence[CAPTURED_AT]}" +%s 2>/dev/null || true)"
  expires_epoch="$(date -d "${evidence[EXPIRES_AT]}" +%s 2>/dev/null || true)"
  [[ "$captured_epoch" =~ ^[0-9]+$ && "$expires_epoch" =~ ^[0-9]+$ ]] || block "${gate}_TIMESTAMP"
  (( captured_epoch <= now + 300 )) || block "${gate}_FUTURE"
  (( now - captured_epoch <= max_age )) || block "${gate}_STALE"
  (( expires_epoch >= now )) || block "${gate}_EXPIRED"
  artifact="${evidence[ARTIFACT_PATH]}"; digest="${evidence[ARTIFACT_SHA256]}"
  [[ -f "$artifact" && ! -L "$artifact" && "$digest" =~ ^[0-9a-f]{64}$ ]] || block "${gate}_ARTIFACT"
  actual="$(sha256sum "$artifact" | awk '{print $1}')"
  [[ "$actual" == "$digest" ]] || block "${gate}_CHECKSUM"
}
validate_evidence "${approved[SHARED_BACKUP_EVIDENCE]}" LOGICAL_BACKUP 3600 BACKUP_EVIDENCE
validate_evidence "${approved[SHARED_OFFHOST_EVIDENCE]}" OFFHOST_READBACK 3600 OFFHOST_EVIDENCE
validate_evidence "${approved[SHARED_RESTORE_EVIDENCE]}" RESTORE_PRECHECK 2592000 RESTORE_EVIDENCE
validate_evidence "${approved[SHARED_ROLLBACK_EVIDENCE]}" ROLLBACK_PRECHECK 2592000 ROLLBACK_EVIDENCE
printf '%s\n' 'CHANGE_AUTHORITY=PASS' 'RPO_RTO_POLICY=PASS' 'RESTART_WINDOW=PASS' 'RECOVERY_EVIDENCE=PASS' 'SHARED_POSTGRES_CUTOVER_GO=YES'
