#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "odoo_addons" / "codestra_crm_call_followup_api"
SCHEMA = ROOT / "api" / "completed_call_v1.schema.json"
CLIENT = ROOT / "integrations" / "odoo_call_followup_client.py"


def main() -> int:
    errors: list[str] = []
    required = [
        ADDON / "__manifest__.py",
        ADDON / "models" / "call_followup_api.py",
        ADDON / "views" / "call_followup_api_views.xml",
        ADDON / "tests" / "test_call_followup_api.py",
        SCHEMA,
        CLIENT,
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    for path in ADDON.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"python syntax error in {path.relative_to(ROOT)}: {exc}")
    try:
        ast.parse(CLIENT.read_text(encoding="utf-8"), filename=str(CLIENT))
    except SyntaxError as exc:
        errors.append(f"python syntax error in {CLIENT.relative_to(ROOT)}: {exc}")

    for path in ADDON.rglob("*.xml"):
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            errors.append(f"xml parse error in {path.relative_to(ROOT)}: {exc}")

    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        if schema.get("additionalProperties") is not False:
            errors.append("completed-call schema must reject additional properties")
        if "event_id" not in schema.get("required", []):
            errors.append("completed-call schema does not require event_id")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid completed-call JSON schema: {exc}")

    model_source = (ADDON / "models" / "call_followup_api.py").read_text(
        encoding="utf-8"
    )
    for token in [
        "register_completed_call_v1",
        "validate_completed_call_v1",
        "get_completed_call_status_v1",
        "get_integration_capabilities",
        "request_fingerprint",
        "_api_assert_or_record_fingerprint",
    ]:
        if token not in model_source:
            errors.append(f"API implementation is missing invariant: {token}")

    client_source = CLIENT.read_text(encoding="utf-8")
    if "max_attempts" not in client_source or "timeout_seconds" not in client_source:
        errors.append("reference client lacks bounded retry or timeout controls")

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_API_VALIDATION=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("ODOO_CRM_CALL_FOLLOWUP_API_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
