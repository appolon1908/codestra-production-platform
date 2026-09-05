#!/usr/bin/env python3
"""Fail-closed validation for the fixed production activation tuple."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NON_ACTIVATABLE_RELEASES = ROOT / "config" / "non-activatable-releases.json"

CHANGE_ID = "CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01"
SUPERSEDED_DIGESTS = {
    "sha256:336c9a31648a0481737fa4bcc3eafb02a22e4b4fc66ba7b8ec1759c087e05e02",
}
ACTIONS = {
    "preflight", "backup", "validate-backup", "restore-test", "stage",
    "canary", "status", "rollback", "collect-evidence",
    "stage-control-plane", "validate-control-plane", "rollback-control-plane",
    "rollout-middleware", "rollback-middleware",
    "activate-control-plane", "enable-production-web-traffic", "disable-production-web-traffic",
    "enable-klyrow-email-delivery", "disable-klyrow-email-delivery",
}
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
    if args.digest in SUPERSEDED_DIGESTS:
        raise ValueError("middleware digest is superseded for new activation")
    if args.change_id != CHANGE_ID:
        raise ValueError("change identifier mismatch")
    revoked = json.loads(NON_ACTIVATABLE_RELEASES.read_text(encoding="utf-8"))
    denied = {entry["protected_sha"] for entry in revoked.get("releases", [])}
    if args.sha in denied:
        raise ValueError("protected release is explicitly non-activatable")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.maintenance_date):
        raise ValueError("exact maintenance date is required")
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
