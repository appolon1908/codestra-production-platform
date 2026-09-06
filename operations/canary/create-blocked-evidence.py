#!/usr/bin/env python3
"""Record unavailable canary evidence without inventing runtime observations.

A checksum-valid NOT_RUN package proves file integrity only. It is not signed
approval, a zero-call observation, rollback proof, or business-flow certification.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION = Path("/etc/codestra/governance/canary.env")
FILES = {
    "AUTHORIZATION-VALIDATION.md": """# Authorization validation

No currently usable one-call authorization scope was established by the local
checker. Missing, inaccessible, malformed, future or expired inputs are blockers.
This checker does not authenticate signatures or independently verify approver
and destination-owner authority. No approval was fabricated or extended.
""",
    "PRE-CALL-GATES.env": """SIGNED_CANARY_GATE=BLOCKED_NOT_VERIFIED
PRECEDING_TECHNICAL_GATES=NOT_RUN
PRODUCTION_ALERT_RECEIVER_GATE=NOT_RUN
PRIMARY_ACKNOWLEDGMENT_GATE=NOT_RUN
SECONDARY_ESCALATION_GATE=NOT_RUN
ALERT_RECOVERY_GATE=NOT_RUN
HUMAN_ESCALATION_ROUTING_GATE=NOT_RUN
PRIMARY_SERVER_ACCESS=NOT_TESTED
APPLICATION_SERVER_SSH_ACCESS=NOT_TESTED
FEATURE_FLAGS=NOT_OBSERVED
MONITORING_RUNTIME=NOT_OBSERVED
ACTIVE_CALL_VALIDATION=NOT_RUN
""",
    "DESTINATION-VALIDATION.md": "# Destination validation\n\n`PROTECTED_DESTINATION_GATE=NOT_RUN`\n\nNo destination was accessed, displayed, queried or dialed by this tool. Destination authorization still requires independent evidence.\n",
    "TRUNK-CALLER-ID-VALIDATION.md": "# Trunk and caller-ID validation\n\n`TRUNK_CONFIGURATION_GATE=NOT_RUN`\n`AUTHORIZED_CALLER_ID_GATE=NOT_RUN`\n\nThis tool did not query or enable any trunk, route or caller ID.\n",
    "DNC-CONSENT-RESULT.md": "# DNC, consent, recording, and callback\n\n`DNC_CANARY_GATE=NOT_RUN`\n`CONSENT_CANARY_GATE=NOT_RUN`\n`RECORDING_SCOPE_GATE=NOT_RUN`\n`CALLBACK_SCOPE_GATE=NOT_RUN`\n\nNo policy check or effect was executed. Policy references and approvals remain required.\n",
    "MONITORING-OPERATOR-RESULT.md": "# Monitoring and operator result\n\n`CANARY_MONITORING_GATE=NOT_RUN`\n`CANARY_OPERATOR_GATE=NOT_RUN`\n\nMonitoring deployment and operator acknowledgment were not inspected. No alert was sent. Absence of observation is not evidence that monitoring is absent or healthy.\n",
    "KILL-SWITCH-RESULT.md": "# Kill-switch result\n\n`PRE_CANARY_KILL_SWITCH_GATE=NOT_RUN`\n\nNo live flag was queried or changed by this tool. Kill-switch behavior is not certified.\n",
    "CALL-RESULT.md": "# Call result\n\n`CALL_EXECUTION_GATE=NOT_RUN`\n`CALL_ATTEMPTS=UNKNOWN`\n`CALL_ATTEMPTS_THIS_TOOL=0`\n\nThis tool cannot dial. It did not query authoritative call counters; it cannot assert that no other process or operator placed a call.\n",
    "EVENT-PATH-RESULT.md": "# Event path result\n\n`CALL_ENDED_EVENT_GATE=NOT_RUN`\n`HISTORICAL_EVENTS=NOT_OBSERVED`\n\nNo call event was generated or replayed by this tool. Historical or quarantined events were not inspected.\n",
    "CALLBACK-RESULT.md": "# Callback result\n\n`CALLBACK_DELIVERY_GATE=NOT_RUN`\n\nNo callback was enabled or delivered by this tool. Global callback counters were not observed.\n",
    "RECONCILIATION.tsv": "component\tstatus\treason\nVICIdial\tNOT_RUN\tno authenticated pilot call readback\nAsterisk\tNOT_RUN\tno authenticated uniqueid readback\nedge-spool\tNOT_RUN\tno pilot event readback\nmiddleware-staging\tNOT_RUN\tno matching event or correlation readback\nOdoo19-staging\tNOT_RUN\tno matching Odoo record readback\nn8n-staging\tNOT_RUN\tno pilot effect observation\nprivate-callback\tNOT_RUN\tno pilot effect observation\n",
    "IDEMPOTENCY-RESULT.md": "# Idempotency result\n\n`CANARY_IDEMPOTENCY_GATE=NOT_RUN`\n\nNo pilot envelope was replayed or read back. Offline tests are not deployed duplicate-suppression proof.\n",
    "DISABLE-CLEANUP.md": "# Disable and cleanup\n\n`POST_CANARY_DISABLE_GATE=NOT_RUN`\n`CANARY_CLEANUP_GATE=NOT_RUN`\n\nThis tool created only these local evidence files. It did not inspect runtime flags or resources, so post-call disable and cleanup are not certified.\n",
    "ROLLBACK-RESULT.md": "# Rollback result\n\n`CANARY_ROLLBACK_GATE=NOT_RUN`\n\nNo restore or rollback rehearsal was performed. Not changing a system is not proof that rollback works.\n",
    "POST-CANARY-OBSERVATION.md": "# Post-canary observation\n\n`POST_CANARY_OBSERVATION_GATE=NOT_RUN`\n\nNo runtime post-call behavior was observed.\n",
    "GATES.env": """SIGNED_CANARY_GATE=BLOCKED_NOT_VERIFIED
PRECEDING_TECHNICAL_GATES=NOT_RUN
PROTECTED_DESTINATION_GATE=NOT_RUN
TRUNK_CONFIGURATION_GATE=NOT_RUN
AUTHORIZED_CALLER_ID_GATE=NOT_RUN
SYNTHETIC_CANARY_FIXTURE_GATE=NOT_RUN
DNC_CANARY_GATE=NOT_RUN
CONSENT_CANARY_GATE=NOT_RUN
RECORDING_SCOPE_GATE=NOT_RUN
CALLBACK_SCOPE_GATE=NOT_RUN
CANARY_MONITORING_GATE=NOT_RUN
CANARY_OPERATOR_GATE=NOT_RUN
PRE_CANARY_KILL_SWITCH_GATE=NOT_RUN
CANARY_GO_NO_GO_GATE=NOT_RUN
CALL_EXECUTION_GATE=NOT_RUN
CALL_ENDED_EVENT_GATE=NOT_RUN
CALLBACK_DELIVERY_GATE=NOT_RUN
CANARY_RECONCILIATION_GATE=NOT_RUN
CANARY_IDEMPOTENCY_GATE=NOT_RUN
POST_CANARY_DISABLE_GATE=NOT_RUN
CANARY_CLEANUP_GATE=NOT_RUN
CANARY_ROLLBACK_GATE=NOT_RUN
POST_CANARY_OBSERVATION_GATE=NOT_RUN
CONTROLLED_CANARY_GATE=NOT_RUN
BUSINESS_FLOW_CERTIFICATION=BLOCKED
ACTIVATION_AUTHORIZED=false
CALL_ATTEMPTS=UNKNOWN
CALL_ATTEMPTS_THIS_TOOL=0
HISTORICAL_EVENTS=NOT_OBSERVED
""",
}


def write_package(package: Path, *, stamp: str, head: str, host: str) -> None:
    """Create new sanitized evidence; never overwrite an existing package."""
    package.mkdir(mode=0o700)
    for name, content in FILES.items():
        (package / name).write_text(content, encoding="utf-8")
    (package / "AUTHORIZATION-VALIDATION.md").write_text(
        FILES["AUTHORIZATION-VALIDATION.md"]
        + f"\nPackage timestamp: `{stamp}`  \nWriter host: `{host}`  \nWriter source commit: `{head}`\n",
        encoding="utf-8",
    )
    names = list(FILES)
    manifest_names = names + ["SHA256SUMS", "verify-evidence.sh", "PACKAGE-MANIFEST"]
    (package / "PACKAGE-MANIFEST").write_text("\n".join(manifest_names) + "\n", encoding="utf-8")
    verifier = """#!/usr/bin/env bash
set -euo pipefail
PACKAGE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
(cd "$PACKAGE"; sha256sum --check SHA256SUMS)
grep -qx 'CONTROLLED_CANARY_GATE=NOT_RUN' "$PACKAGE/GATES.env"
grep -qx 'BUSINESS_FLOW_CERTIFICATION=BLOCKED' "$PACKAGE/GATES.env"
grep -qx 'ACTIVATION_AUTHORIZED=false' "$PACKAGE/GATES.env"
grep -qx 'CALL_ATTEMPTS=UNKNOWN' "$PACKAGE/GATES.env"
grep -qx 'CALL_ATTEMPTS_THIS_TOOL=0' "$PACKAGE/GATES.env"
if grep -Eq '(^|_)GATE=PASS$' "$PACKAGE/GATES.env"; then exit 1; fi
echo "blocked_evidence_package_integrity=VERIFIED business_flow_certified=false"
"""
    verifier_path = package / "verify-evidence.sh"
    verifier_path.write_text(verifier, encoding="utf-8")
    verifier_path.chmod(0o700)
    checksums = [f"{hashlib.sha256((package / name).read_bytes()).hexdigest()}  {name}"
                 for name in names + ["verify-evidence.sh", "PACKAGE-MANIFEST"]]
    (package / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: create-blocked-evidence.py PACKAGE_PATH", file=sys.stderr)
        return 2
    package = Path(sys.argv[1]).resolve()
    if not str(package).startswith("/root/signed-one-call-canary-evidence-"):
        print("refusing unexpected evidence path", file=sys.stderr)
        return 2
    validator = ROOT / "operations/canary/validate-authorization.py"
    result = subprocess.run([str(validator), str(AUTHORIZATION)], text=True, capture_output=True, check=False)
    if result.returncode == 0:
        print("refusing blocked package: scope validates; independent signature and runtime evidence still required", file=sys.stderr)
        return 2
    if package.exists():
        print("refusing to overwrite evidence package", file=sys.stderr)
        return 2
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    write_package(package, stamp=datetime.now(timezone.utc).isoformat(), head=head, host=os.uname().nodename)
    print(f"blocked_evidence_package={package} business_flow_certified=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
