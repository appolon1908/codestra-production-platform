#!/usr/bin/env python3
"""Create a sanitized Phase 6 NOT_RUN package when authorization is unavailable."""

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

No accessible signed Phase 6 authorization record exists at `/etc/codestra/governance/canary.env`. Mandatory approvals, signature, approver authority, active window, bounded resources, protected destination, caller ID, operator confirmation, DNC zero-match approval, rollback ownership, and emergency-disable ownership are `NOT_PROVIDED` or `INACCESSIBLE`.

No approval was self-signed, extended, reinterpreted, or fabricated.
""",
    "PRE-CALL-GATES.env": """SIGNED_CANARY_GATE=BLOCKED_EXTERNAL_PREREQUISITE
PRECEDING_TECHNICAL_GATES=BLOCKED_EXTERNAL_PREREQUISITE
PRODUCTION_ALERT_RECEIVER_GATE=BLOCKED_EXTERNAL_PREREQUISITE
PRIMARY_ACKNOWLEDGMENT_GATE=BLOCKED_EXTERNAL_PREREQUISITE
SECONDARY_ESCALATION_GATE=BLOCKED_EXTERNAL_PREREQUISITE
ALERT_RECOVERY_GATE=NOT_RUN
HUMAN_ESCALATION_ROUTING_GATE=BLOCKED_EXTERNAL_PREREQUISITE
PRIMARY_SERVER_ACCESS=INACCESSIBLE
APPLICATION_SERVER_SSH_ACCESS=INACCESSIBLE
FEATURE_FLAGS=FALSE_WHERE_OBSERVED
MONITORING_RUNTIME=ABSENT
ACTIVE_CALL_VALIDATION=INACCESSIBLE
""",
    "DESTINATION-VALIDATION.md": "# Destination validation\n\n`PROTECTED_DESTINATION_GATE=NOT_RUN`\n\nNo protected destination reference or zero-match approval was provided. No destination was accessed, normalized, displayed, queried, or dialed.\n",
    "TRUNK-CALLER-ID-VALIDATION.md": "# Trunk and caller-ID validation\n\n`TRUNK_CONFIGURATION_GATE=NOT_RUN`  \n`AUTHORIZED_CALLER_ID_GATE=NOT_RUN`\n\nNo approved trunk, carrier route, caller ID, or caller-ID approval was provided. No call route was enabled.\n",
    "DNC-CONSENT-RESULT.md": "# DNC, consent, recording, and callback\n\n`DNC_CANARY_GATE=NOT_RUN`  \n`RECORDING_SCOPE_GATE=NOT_RUN`  \n`CALLBACK_SCOPE_GATE=NOT_RUN`\n\nNo destination or authorization was available. DNC uncertainty therefore failed closed. Recording and callback execution remained disabled.\n",
    "MONITORING-OPERATOR-RESULT.md": "# Monitoring and operator result\n\n`CANARY_MONITORING_GATE=BLOCKED_EXTERNAL_PREREQUISITE`  \n`CANARY_OPERATOR_GATE=BLOCKED_EXTERNAL_PREREQUISITE`\n\nThe production monitoring stack is not deployed, live receiver/human acknowledgment gates remain blocked, and no attributable canary operator confirmation exists. No pre-canary alert was sent.\n",
    "KILL-SWITCH-RESULT.md": "# Kill-switch result\n\n`PRE_CANARY_KILL_SWITCH_GATE=NOT_RUN`\n\nNo bounded fixture or signed operator window exists. The fail-closed baseline was not relaxed and no call-capable state was enabled.\n",
    "CALL-RESULT.md": "# Call result\n\n`CALL_EXECUTION_GATE=NOT_RUN`\n\nCall attempts consumed: **0 of 1**. No call was placed and no one-call budget was consumed.\n",
    "EVENT-PATH-RESULT.md": "# Event path result\n\n`CALL_ENDED_EVENT_GATE=NOT_RUN`\n\nNo call event was generated or replayed. The 1,110 quarantined historical events were not accessed or mutated.\n",
    "CALLBACK-RESULT.md": "# Callback result\n\n`CALLBACK_DELIVERY_GATE=NOT_RUN`\n\nNo callback was enabled or delivered.\n",
    "RECONCILIATION.tsv": "component\tstatus\treason\nVICIdial\tNOT_RUN\tcall not authorized\nAsterisk\tNOT_RUN\tcall not authorized\nedge-spool\tNOT_RUN\tno canary event\nmiddleware-staging\tNOT_RUN\tno canary event\nOdoo19-staging\tNOT_RUN\tno canary event\nn8n-staging\tNOT_RUN\tno canary event\nprivate-callback\tNOT_RUN\tcallback disabled\n",
    "IDEMPOTENCY-RESULT.md": "# Idempotency result\n\n`CANARY_IDEMPOTENCY_GATE=NOT_RUN`\n\nNo generated canary envelope exists. Nothing was replayed.\n",
    "DISABLE-CLEANUP.md": "# Disable and cleanup\n\n`POST_CANARY_DISABLE_GATE=PASS`  \n`CANARY_CLEANUP_GATE=PASS`\n\nNo canary capability was enabled, no call/session/credential/worker was created, and all observed application safety flags remained false. No temporary call resource required removal.\n",
    "ROLLBACK-RESULT.md": "# Rollback result\n\n`CANARY_ROLLBACK_GATE=PASS`\n\nThe pre-canary state was never changed, so rollback is the unchanged fail-closed baseline. No application or call configuration was modified.\n",
    "POST-CANARY-OBSERVATION.md": "# Post-canary observation\n\n`POST_CANARY_OBSERVATION_GATE=NOT_RUN`\n\nThere was no canary call to observe. No claim about post-call behavior is made.\n",
    "GATES.env": """SIGNED_CANARY_GATE=BLOCKED_EXTERNAL_PREREQUISITE
PRECEDING_TECHNICAL_GATES=BLOCKED_EXTERNAL_PREREQUISITE
PROTECTED_DESTINATION_GATE=NOT_RUN
TRUNK_CONFIGURATION_GATE=NOT_RUN
AUTHORIZED_CALLER_ID_GATE=NOT_RUN
SYNTHETIC_CANARY_FIXTURE_GATE=NOT_RUN
DNC_CANARY_GATE=NOT_RUN
RECORDING_SCOPE_GATE=NOT_RUN
CALLBACK_SCOPE_GATE=NOT_RUN
CANARY_MONITORING_GATE=BLOCKED_EXTERNAL_PREREQUISITE
CANARY_OPERATOR_GATE=BLOCKED_EXTERNAL_PREREQUISITE
PRE_CANARY_KILL_SWITCH_GATE=NOT_RUN
CANARY_GO_NO_GO_GATE=NOT_RUN
CALL_EXECUTION_GATE=NOT_RUN
CALL_ENDED_EVENT_GATE=NOT_RUN
CALLBACK_DELIVERY_GATE=NOT_RUN
CANARY_RECONCILIATION_GATE=NOT_RUN
CANARY_IDEMPOTENCY_GATE=NOT_RUN
POST_CANARY_DISABLE_GATE=PASS
CANARY_CLEANUP_GATE=PASS
CANARY_ROLLBACK_GATE=PASS
POST_CANARY_OBSERVATION_GATE=NOT_RUN
CONTROLLED_CANARY_GATE=NOT_RUN
CALL_ATTEMPTS=0
HISTORICAL_EVENTS=1110_UNCHANGED
""",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: create-blocked-evidence.py PACKAGE_PATH", file=sys.stderr)
        return 2
    package = Path(sys.argv[1]).resolve()
    if not str(package).startswith("/root/signed-one-call-canary-evidence-"):
        print("refusing unexpected evidence path", file=sys.stderr)
        return 2
    validator = ROOT / "operations/canary/validate-authorization.py"
    result = subprocess.run(
        [str(validator), str(AUTHORIZATION)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print("refusing blocked package: authorization currently validates", file=sys.stderr)
        return 2
    if package.exists():
        print("refusing to overwrite evidence package", file=sys.stderr)
        return 2
    package.mkdir(mode=0o700)
    stamp = datetime.now(timezone.utc).isoformat()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for name, content in FILES.items():
        (package / name).write_text(content)
    (package / "AUTHORIZATION-VALIDATION.md").write_text(
        FILES["AUTHORIZATION-VALIDATION.md"]
        + f"\nEvidence timestamp: `{stamp}`  \nHost: `{os.uname().nodename}`  \nCommit: `{head}`\n"
    )
    names = list(FILES)
    manifest_names = names + ["SHA256SUMS", "verify-evidence.sh", "PACKAGE-MANIFEST"]
    (package / "PACKAGE-MANIFEST").write_text("\n".join(manifest_names) + "\n")
    verifier = """#!/usr/bin/env bash
set -euo pipefail
PACKAGE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
(
  cd "$PACKAGE"
  sha256sum --check SHA256SUMS
)
grep -qx 'CONTROLLED_CANARY_GATE=NOT_RUN' "$PACKAGE/GATES.env"
grep -qx 'CALL_ATTEMPTS=0' "$PACKAGE/GATES.env"
echo "signed_canary_blocked_evidence=VERIFIED"
"""
    verifier_path = package / "verify-evidence.sh"
    verifier_path.write_text(verifier)
    verifier_path.chmod(0o700)
    checksum_names = names + ["verify-evidence.sh", "PACKAGE-MANIFEST"]
    checksum_lines = []
    for name in checksum_names:
        digest = hashlib.sha256((package / name).read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {name}")
    (package / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n")
    print(f"blocked_evidence_package={package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
