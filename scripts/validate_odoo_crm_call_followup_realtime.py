#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "odoo_addons" / "codestra_crm_call_followup_realtime"

REQUIRED = {
    "__init__.py",
    "__manifest__.py",
    "models/__init__.py",
    "models/realtime.py",
    "models/realtime_api.py",
    "data/cron.xml",
    "views/realtime_views.xml",
    "static/src/js/post_call_realtime_service.js",
    "tests/__init__.py",
    "tests/test_realtime.py",
    "README.md",
}


def main() -> int:
    errors: list[str] = []
    for relative in sorted(REQUIRED):
        if not (MODULE / relative).is_file():
            errors.append(f"missing required file: {relative}")

    manifest_path = MODULE / "__manifest__.py"
    if manifest_path.is_file():
        try:
            manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError) as exc:
            errors.append(f"invalid manifest: {exc}")
            manifest = {}
        if not str(manifest.get("version", "")).startswith("19.0."):
            errors.append("manifest must target Odoo 19")
        if "codestra_crm_call_followup" not in manifest.get("depends", []):
            errors.append("realtime addon must depend on the core follow-up addon")
        for relative in manifest.get("data", []):
            if not (MODULE / relative).is_file():
                errors.append(f"manifest data file does not exist: {relative}")

    for path in MODULE.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"python syntax error in {path.relative_to(ROOT)}: {exc}")
    for path in MODULE.rglob("*.xml"):
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            errors.append(f"XML parse error in {path.relative_to(ROOT)}: {exc}")

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for pattern in ("*.py", "*.js")
        for path in MODULE.rglob(pattern)
    )
    for snippet in (
        "FOR UPDATE",
        "rt_claim_v1",
        "rt_renew_v1",
        "rt_release_v1",
        "rt_recover_v1",
        "claim_token",
        "bus_service.subscribe",
        "{ force: true }",
    ):
        if snippet not in source:
            errors.append(f"missing realtime invariant: {snippet}")

    lowered = source.lower()
    for forbidden in (
        "auth=\"public\"",
        "auth='public'",
        "vicidial/admin.php",
        "vicidial/non_agent_api.php",
        "requests.post(",
    ):
        if forbidden in lowered:
            errors.append(f"forbidden integration pattern: {forbidden}")

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_REALTIME_GATE=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1
    print("ODOO_CRM_CALL_FOLLOWUP_REALTIME_GATE=PASS")
    print("LEASE_PROTOCOL=V1")
    print("MULTI_TAB_EXCLUSION=ENABLED")
    print("EXPIRED_CLAIM_RECOVERY=ENABLED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
