#!/usr/bin/env python3
"""Emit one repository-pinned quarantined tuple for recovery-only dispatch."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "config" / "signing-authority-rotation.json"
RECOVERY_ACTIONS = {"status", "collect-evidence", "disable-production-web-traffic", "disable-klyrow-email-delivery"}


def validated_tuple(action: str) -> dict[str, str]:
    if action not in RECOVERY_ACTIONS:
        raise ValueError("action is not recovery-only")
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    if record.get("status") != "NON_ACTIVATABLE" or record.get("production_delivery_authorized") is not False:
        raise ValueError("release quarantine is invalid")
    target = record.get("installed_tuple")
    required = {"protected_sha", "image_digest", "change_id", "maintenance_date"}
    if not isinstance(target, dict) or set(target) != required:
        raise ValueError("exact installed tuple is required")
    patterns = {"protected_sha": r"[0-9a-f]{40}", "image_digest": r"sha256:[0-9a-f]{64}", "change_id": r"CHG-[0-9]{8}-CODESTRA-PRODUCTION-ACTIVATION-[0-9]{2}", "maintenance_date": r"20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])"}
    if any(re.fullmatch(patterns[key], value) is None for key, value in target.items()):
        raise ValueError("installed tuple is malformed")
    if target["protected_sha"] != record.get("blocked_release_sha"):
        raise ValueError("quarantined SHA mismatch")
    return {"action": action, **target}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=sorted(RECOVERY_ACTIONS))
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        values = validated_tuple(args.action)
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as stream:
                for key, value in values.items():
                    stream.write(f"{key}={value}\n")
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"recovery request rejected: {error}")
        return 2
    print("recovery request accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
