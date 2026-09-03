#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ADDON = (
    ROOT
    / "odoo_addons"
    / "codestra_crm_call_followup_automation"
)
SCHEMA = (
    ROOT
    / "api"
    / "call_followup_automation_event_v1.schema.json"
)
HARDENING = ADDON / "models" / "hardening.py"
MIDDLEWARE_PACKAGE = ROOT / "control_plane_service" / "__init__.py"
MIDDLEWARE_TEST = (
    ROOT / "tests" / "test_call_followup_automation_middleware_contract.py"
)
WIRE_EVENT_TYPES = {
    "call_followup.completed",
    "call_followup.callback_scheduled",
    "call_followup.appointment_scheduled",
    "call_followup.email_queued",
    "call_followup.calendar_rescheduled",
    "call_followup.calendar_cancelled",
}


def main() -> int:
    errors: list[str] = []
    required = [
        ADDON / "__manifest__.py",
        ADDON / "models" / "outbox.py",
        ADDON / "models" / "calendar_event.py",
        HARDENING,
        ADDON / "wizard" / "post_call_wizard.py",
        ADDON / "security" / "ir.model.access.csv",
        ADDON / "security" / "rules.xml",
        ADDON / "data" / "ir_cron_data.xml",
        ADDON / "views" / "outbox_views.xml",
        ADDON / "tests" / "test_outbox.py",
        ADDON / "tests" / "test_hardening.py",
        SCHEMA,
        MIDDLEWARE_PACKAGE,
        MIDDLEWARE_TEST,
    ]
    for path in required:
        if not path.is_file():
            errors.append(
                f"missing required file: {path.relative_to(ROOT)}"
            )

    for path in ADDON.rglob("*.py"):
        try:
            ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
        except SyntaxError as exc:
            errors.append(
                f"python syntax error in "
                f"{path.relative_to(ROOT)}: {exc}"
            )

    for path in ADDON.rglob("*.xml"):
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            errors.append(
                f"xml parse error in "
                f"{path.relative_to(ROOT)}: {exc}"
            )

    try:
        schema = json.loads(
            SCHEMA.read_text(encoding="utf-8")
        )
        if schema.get("additionalProperties") is not False:
            errors.append(
                "automation schema must reject extra envelope fields"
            )
        event_types = set(
            schema.get("properties", {})
            .get("event_type", {})
            .get("enum", [])
        )
        if event_types != WIRE_EVENT_TYPES:
            errors.append(
                "automation schema does not define the exact "
                "call_followup.* namespace"
            )
        metadata = (
            schema.get("properties", {})
            .get("metadata", {})
        )
        if set(metadata.get("required", [])) != {
            "source",
            "logical_event_id",
        }:
            errors.append(
                "automation schema metadata is not stable across retries"
            )
        if "delivery_attempt" in metadata.get("properties", {}):
            errors.append(
                "delivery attempts must not alter signed producer content"
            )
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid automation schema: {exc}")

    source = (
        ADDON / "models" / "outbox.py"
    ).read_text(encoding="utf-8")
    for token in [
        "FOR UPDATE SKIP LOCKED",
        "state = 'processing'",
        "_write_if_claimed",
        "_NoRedirectHandler",
        "allowed_hosts",
        "codestra.call_followup_automation.enabled",
        "webhook_secret_file",
        "Idempotency-Key",
        "X-Signature",
        "manual_retry_count",
        "MANUAL_RETRY_ATTEMPTS",
        "max_attempts",
        '"dead" if permanent or exhausted else "retry"',
    ]:
        if token not in source:
            errors.append(
                f"automation outbox is missing invariant: {token}"
            )
    for forbidden in [
        '"email_body":',
        '"notes":',
        "force_send=True",
        "urllib.request.urlopen(",
    ]:
        if forbidden in source:
            errors.append(
                "automation payload may expose forbidden "
                f"content or behavior: {forbidden}"
            )

    hardening_source = HARDENING.read_text(encoding="utf-8")
    for token in [
        'MIDDLEWARE_SOURCE = "odoo"',
        '"post_call.completed": "call_followup.completed"',
        "codestra-middleware-attempt:",
        '"logical_event_id": self.event_id',
        "replayed_event_id",
        "reconciled_replay",
        "O_NOFOLLOW",
        "O_NONBLOCK",
        "os.fstat",
        "stat.S_ISREG",
        "parsed.query",
        "accepted_event_ids",
    ]:
        if token not in hardening_source:
            errors.append(
                f"automation hardening is missing invariant: {token}"
            )
    if '"delivery_attempt"' in hardening_source:
        errors.append(
            "automation hardening still signs a mutable delivery attempt"
        )
    if 'config["tenant_id"].encode' in hardening_source:
        errors.append(
            "automation HMAC still signs tenant_id in the source slot"
        )

    middleware_source = MIDDLEWARE_PACKAGE.read_text(
        encoding="utf-8"
    )
    if '"call_followup."' not in middleware_source:
        errors.append(
            "middleware does not register the call_followup.* Odoo prefix"
        )

    if errors:
        print(
            "ODOO_CRM_CALL_FOLLOWUP_AUTOMATION_VALIDATION=FAIL"
        )
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "ODOO_CRM_CALL_FOLLOWUP_AUTOMATION_VALIDATION=PASS"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
