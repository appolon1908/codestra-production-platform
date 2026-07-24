#!/usr/bin/env python3
"""Fail-closed validation for production governance references."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED = (
    "PRODUCTION_ALERT_RECEIVER",
    "PRIMARY_ESCALATION_OWNER",
    "PRIMARY_ESCALATION_CONTACT_REFERENCE",
    "SECONDARY_ESCALATION_OWNER",
    "SECONDARY_ESCALATION_CONTACT_REFERENCE",
    "RECOVERY_NOTIFICATION_RECEIVER",
    "RECOVERY_RECEIVER_OWNER_REFERENCE",
    "ALERT_ESCALATION_POLICY_REFERENCE",
    "ALERT_ACKNOWLEDGMENT_TIMEOUT_MINUTES",
    "SECONDARY_ESCALATION_DELAY_MINUTES",
    "MONITORING_APPROVER",
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
    numeric = ("ALERT_ACKNOWLEDGMENT_TIMEOUT_MINUTES", "SECONDARY_ESCALATION_DELAY_MINUTES")
    try:
        if any(int(values[key]) <= 0 for key in numeric):
            raise ValueError
    except ValueError:
        print("invalid positive integer governance timing", file=sys.stderr)
        return 2
    print(f"governance_references=validated count={len(REQUIRED)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
