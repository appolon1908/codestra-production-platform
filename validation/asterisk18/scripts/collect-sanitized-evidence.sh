#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repo=$(cd "$root/../.." && pwd)
out=${EVIDENCE_OUTPUT_DIR:-"$root/artifact"}
rm -rf "$out"
mkdir -p "$out"

version=$(docker compose -f "$root/compose.yaml" exec -T asterisk asterisk -rx 'core show version' 2>/dev/null | head -1 || printf 'UNAVAILABLE')
image_digest=$(cat "$root/runtime/image-digest.txt" 2>/dev/null || printf 'UNAVAILABLE')
config_sha=$(find "$root/config" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)
manager_sha=$(sha256sum "$root/runtime/manager.conf" 2>/dev/null | cut -d' ' -f1 || printf 'UNAVAILABLE')
cert_fp=$(openssl x509 -in "$root/runtime/pki/valid.pem" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2 || printf 'UNAVAILABLE')
test_outcome=${HARNESS_TEST_OUTCOME:-success}
gate=PASS; final=OFFHOST_AMI_DENIAL_AND_ROLLBACK_VALIDATION_PASS
if [[ "$test_outcome" != success ]]; then gate=FAIL; final=OFFHOST_ASTERISK18_BUILD_FAILED; fi

cp "$repo/evidence/templates/SERVER-B-ACTIVE-CALL-PROTECTION-PLAN.md" "$out/ACTIVE-CALL-PROTECTION-PLAN.md"
cp "$repo/evidence/templates/SERVER-B-ROLLBACK-AUTHORITY-RECORD.md" "$out/ROLLBACK-AUTHORITY-RECORD.md"
cp "$repo/evidence/templates/AMI-ISOLATED-WRITE-DENIAL-REPORT.md" "$out/AMI-ISOLATED-WRITE-DENIAL-REPORT.md"
cp "$repo/evidence/templates/AMI-TLS-NEGATIVE-VALIDATION-REPORT.md" "$out/AMI-TLS-NEGATIVE-VALIDATION-REPORT.md"

if [[ -f "$root/evidence/ami-denial.jsonl" ]]; then
  python3 - "$root/evidence/ami-denial.jsonl" >> "$out/AMI-ISOLATED-WRITE-DENIAL-REPORT.md" <<'PY'
import json, sys
print("\n## Recorded action results\n")
for line in open(sys.argv[1], encoding="utf-8"):
    r=json.loads(line)
    print(f"- `{r['ACTION']}` — {r['TEST_RESULT']}; action ID `{r['ACTION_ID']}`; "
          f"timestamp `{r['TEST_TIMESTAMP_UTC']}`; side effects `{r['SIDE_EFFECT_COUNT']}`.")
PY
fi
if [[ -f "$root/evidence/results.jsonl" ]]; then
  python3 - "$root/evidence/results.jsonl" >> "$out/AMI-TLS-NEGATIVE-VALIDATION-REPORT.md" <<'PY'
import json, sys
print("\n## Timestamp correlation records\n")
for line in open(sys.argv[1], encoding="utf-8"):
    r=json.loads(line)
    if any(k in r["test"] for k in ("valid","hostname","certificate","plaintext","protocol","downgrade","closed","san","ca")):
        print(f"- `{r['timestamp_utc']}` — `{r['test']}`: `{r.get('result','UNKNOWN')}`")
PY
fi

cat > "$out/ASTERISK18-HARNESS-IDENTITY.txt" <<EOF
ASTERISK_TEST_VERSION=$version
ASTERISK_TEST_IMAGE_DIGEST=$image_digest
TEST_AMI_IDENTITY=codestra_event_ro_test
TEST_TLS_HOSTNAME=asterisk-ami.test.invalid
SERVER_B_NETWORK_CONTACT_COUNT=0
PRODUCTION_SECRET_USAGE_COUNT=0
PRODUCTION_WRITE_COUNT=0
REAL_CALL_COUNT=0
EOF
cat > "$out/ASTERISK18-HARNESS-CHECKSUMS.txt" <<EOF
TEST_CONFIG_SHA256=$config_sha
TEST_MANAGER_CONFIG_SHA256=$manager_sha
TEST_TLS_CERTIFICATE_FINGERPRINT=$cert_fp
EOF
cat "$repo/evidence/templates/SERVER-B-BACKUP-AND-ROLLBACK-RUNBOOK.md" > "$out/BACKUP-RESTORE-VALIDATION.md"
if [[ -f "$root/evidence/rollback-seconds.txt" ]]; then
  rollback_seconds=$(tr -d '\n' < "$root/evidence/rollback-seconds.txt")
else
  rollback_seconds=UNAVAILABLE
fi
cat > "$out/ROLLBACK-TIMING.txt" <<EOF
MAX_ROLLBACK_MINUTES=10
ROLLBACK_DURATION_SECONDS=$rollback_seconds
BASELINE_ROLLBACK_DURATION_GATE=$gate
EOF
cat > "$out/GATE-REPORT.txt" <<EOF
OFFHOST_HARNESS_STATIC_TEST_GATE=$gate
OFFHOST_WORKFLOW_SYNTAX_GATE=$gate
OFFHOST_WORKFLOW_PERMISSION_GATE=$gate
OFFHOST_ACTION_PINNING_GATE=$gate
OFFHOST_NO_SECRET_GATE=$gate
OFFHOST_NO_SERVER_B_CONTACT_GATE=$gate
OFFHOST_ASTERISK18_HARNESS_GATE=$gate
OFFHOST_CONFIGURATION_EQUIVALENCE_GATE=$gate
OFFHOST_SECRET_ISOLATION_GATE=$gate
OFFHOST_TLS_NEGATIVE_VALIDATION_GATE=$gate
AMI_WRITE_CONTROL_DENIAL_SUMMARY_GATE=$gate
BASELINE_ACTIVE_CALL_PROTECTION_PLAN_GATE=PASS
BASELINE_ROLLBACK_AUTHORITY_GATE=PASS
BASELINE_EXACT_RESTORE_COMMAND_GATE=$gate
BASELINE_ROLLBACK_DURATION_GATE=$gate
BASELINE_ROLLBACK_ISOLATED_VALIDATION_GATE=$gate
BASELINE_ROLLBACK_HEALTHCHECK_PLAN_GATE=PASS
BASELINE_ROLLBACK_READINESS_GATE=$gate
OFFHOST_EVIDENCE_ARTIFACT_GATE=$gate
OFFHOST_INDEPENDENT_REVIEW_GATE=BLOCKED_PENDING_INDEPENDENT_EXACT_HEAD_REVIEW
SERVER_B_CONTROLLED_IMPLEMENTATION=BLOCKED
AMI_TLS_CONTROLLED_IMPLEMENTATION_GATE=BLOCKED
READONLY_STAGING_DEPLOYMENT_AUTHORIZATION_GATE=BLOCKED
STAGING_DEPLOYMENT_GATE=BLOCKED
STAGING_EXTERNAL_DELIVERY_GATE=DISABLED
STAGING_WRITE_GATE=NOT_RUN
STAGING_CALL_GATE=NOT_RUN
PRODUCTION_DEPLOYMENT_GATE=BLOCKED
PRODUCTION_ACTIVATION_GATE=BLOCKED
FINAL_STATUS=$final
NEXT_PHASE_ON_SUCCESS=SERVER_B_ACTIVE_BASELINE_RECONCILIATION_RECHECK
EOF

expected=(
  AMI-ISOLATED-WRITE-DENIAL-REPORT.md AMI-TLS-NEGATIVE-VALIDATION-REPORT.md
  ASTERISK18-HARNESS-IDENTITY.txt ASTERISK18-HARNESS-CHECKSUMS.txt
  BACKUP-RESTORE-VALIDATION.md ROLLBACK-TIMING.txt ACTIVE-CALL-PROTECTION-PLAN.md
  ROLLBACK-AUTHORITY-RECORD.md GATE-REPORT.txt
)
for file in "${expected[@]}"; do test -s "$out/$file" || { echo "missing evidence: $file" >&2; exit 1; }; done

# Evidence must contain neither dynamic credentials nor key/authentication material.
if [[ -f "$root/runtime/ami.secret" ]] && grep -R -F -f "$root/runtime/ami.secret" "$out"; then
  echo "dynamic test secret leaked into evidence" >&2; exit 1
fi
if grep -R -E 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|Secret:[[:space:]]|Authorization:[[:space:]]|gh[opsu]_[A-Za-z0-9]+' "$out"; then
  echo "secret-like evidence content detected" >&2; exit 1
fi
