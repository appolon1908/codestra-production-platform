#!/usr/bin/env python3
"""Fail-closed validation for production governance references."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED = (
    "PRODUCTION_ALERT_RECEIVER",
    "PRIMARY_ESCALATION_OWNER",
    "PRIMARY_PROTECTED_CONTACT",
    "SECONDARY_ESCALATION_OWNER",
    "SECONDARY_PROTECTED_CONTACT",
    "RECOVERY_NOTIFICATION_RECEIVER",
    "ALERT_ESCALATION_POLICY_REFERENCE",
    "PRIMARY_ACKNOWLEDGMENT_WINDOW",
    "SECONDARY_ESCALATION_WINDOW",
    "MONITORING_APPROVAL_REFERENCE",
    "AFTER_HOURS_POLICY_REFERENCE",
    "INCIDENT_RESPONSE_OWNER",
    "MONITORING_OWNER",
    "MONITORING_CHANGE_ID",
    "MONITORING_MAINTENANCE_WINDOW",
    "MONITORING_RETENTION_POLICY",
    "API_PERMISSION_APPROVER",
    "DNC_POLICY_REFERENCE",
    "DNC_TEST_APPROVER",
    "RECORDING_POLICY_REFERENCE",
    "RECORDING_RETENTION_POLICY",
    "SECURITY_APPROVER",
    "MAINTENANCE_APPROVER",
    "RISK_ACCEPTANCE_OWNER",
    "PRODUCTION_ACTIVATION_APPROVER",
    "FINAL_CHANGE_ID",
    "FINAL_PRODUCTION_WINDOW",
    "ROLLBACK_DECISION_OWNER",
)
INVALID = re.compile(r"(?:^|[_\s-])(TBD|TODO|UNKNOWN|PLACEHOLDER|BLOCKED|ABSENT|NONE)(?:$|[_\s-])", re.I)


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip("'\"")
    return values


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-governance.py PATH", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"governance reference file is missing: {path}", file=sys.stderr)
        return 2
    values = parse(path)
    invalid = [
        key for key in REQUIRED
        if not values.get(key) or INVALID.search(values[key])
    ]
    if invalid:
        print("invalid or missing governance references: " + ", ".join(invalid), file=sys.stderr)
        return 2
    print(f"governance_references=validated count={len(REQUIRED)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
