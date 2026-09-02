#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "odoo_addons" / "codestra_crm_call_followup_ux"
CALL_FOLLOWUP_VIEW = ADDON / "views" / "call_followup_views.xml"


def main() -> int:
    errors = []
    required = [
        ADDON / "__manifest__.py",
        ADDON / "models" / "call_followup.py",
        ADDON / "wizard" / "post_call_wizard.py",
        ADDON / "views" / "post_call_wizard_views.xml",
        CALL_FOLLOWUP_VIEW,
        ADDON / "data" / "ir_cron_data.xml",
        ADDON / "static" / "src" / "js" / "post_call_service.js",
        ADDON / "tests" / "test_call_followup_ux.py",
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    for path in ADDON.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"python syntax error in {path.relative_to(ROOT)}: {exc}")

    for path in ADDON.rglob("*.xml"):
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            errors.append(f"xml parse error in {path.relative_to(ROOT)}: {exc}")
        source = path.read_text(encoding="utf-8")
        if "@string=" in source:
            errors.append(
                f"Odoo inherited view selector depends on translated string: {path.relative_to(ROOT)}"
            )

    if CALL_FOLLOWUP_VIEW.is_file():
        view_source = CALL_FOLLOWUP_VIEW.read_text(encoding="utf-8")
        stable_anchor = "//field[@name='schedule_kind']/ancestor::group[1]"
        if stable_anchor not in view_source:
            errors.append(
                "UX reminder group must use the stable schedule_kind field anchor"
            )

    model_source = (ADDON / "models" / "call_followup.py").read_text(
        encoding="utf-8"
    )
    for token in [
        "ALLOWED_SNOOZE_MINUTES",
        "get_post_call_popup_state",
        "_cron_release_snoozed_followups",
        "POST_CALL_BUS_CHANNEL",
    ]:
        if token not in model_source:
            errors.append(f"UX model is missing invariant: {token}")

    js_source = (
        ADDON / "static" / "src" / "js" / "post_call_service.js"
    ).read_text(encoding="utf-8")
    for token in [
        "force: true",
        "get_post_call_popup_state",
        "get_pending_post_call_actions",
        "browser.addEventListener",
        "browser.setInterval",
    ]:
        if token not in js_source:
            errors.append(f"enhanced popup service is missing invariant: {token}")

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_UX_VALIDATION=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("ODOO_CRM_CALL_FOLLOWUP_UX_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
