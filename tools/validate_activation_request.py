#!/usr/bin/env python3
"""Fail-closed validation for the fixed production activation tuple."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

CHANGE_ID = "CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01"
ACTIONS = {"preflight", "backup", "validate-backup", "restore-test", "stage", "canary", "status", "rollback", "collect-evidence"}
READ_ONLY_ACTIONS = {"preflight", "status", "collect-evidence"}
REQUIRED_FALSE_FLAGS = {
    "CALLBACK_DISPATCH",
    "ENABLE_EXTERNAL_DELIVERY",
    "ENABLE_VICIDIAL_WRITES",
    "GENERAL_AI_DIALING",
    "LIVE_CALL_CONTROL",
    "LIVE_WRITE",
    "N8N_DELIVERY_ENABLED",
    "ODOO_DELIVERY_ENABLED",
    "ODOO_WRITE",
    "PRODUCTION_DIALING",
    "SEND_EVENTS",
}


def validate(args: argparse.Namespace) -> None:
    if args.action not in ACTIONS:
        raise ValueError("unsupported action")
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        raise ValueError("protected SHA is malformed")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.digest):
        raise ValueError("image digest is malformed")
    if args.change_id != CHANGE_ID:
        raise ValueError("change identifier mismatch")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.maintenance_date):
        raise ValueError("exact maintenance date is required")
    date = dt.date.fromisoformat(args.maintenance_date)
    if date < dt.date.today():
        raise ValueError("maintenance date is in the past")
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("commit") != args.sha:
        raise ValueError("deployment manifest SHA mismatch")
    if manifest.get("release_tuple", {}).get("middleware_image_digest") != args.digest:
        raise ValueError("deployment manifest digest mismatch")
    flags = manifest.get("required_flags")
    if not isinstance(flags, dict) or set(flags) != REQUIRED_FALSE_FLAGS:
        raise ValueError("release has incomplete fail-closed flags")
    if any(value is not False for value in flags.values()):
        raise ValueError("release does not default fail closed")
    if args.action not in READ_ONLY_ACTIONS:
        now = dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo("America/New_York"))
        if now.date() != date or not (0 <= now.hour < 4):
            raise ValueError("state-changing action is outside maintenance window")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--change-id", required=True)
    parser.add_argument("--maintenance-date", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    try:
        validate(args)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"activation request rejected: {error}")
        return 2
    print("activation request accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
