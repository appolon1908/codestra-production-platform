#!/usr/bin/env python3
"""Static release gate for the Codestra Odoo 19 CRM call follow-up addon."""

from __future__ import annotations

import ast
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "odoo_addons" / "codestra_crm_call_followup"
MANIFEST = MODULE / "__manifest__.py"

REQUIRED_FILES = {
    "__init__.py",
    "__manifest__.py",
    "models/__init__.py",
    "models/call_followup.py",
    "models/calendar_event.py",
    "models/crm_lead.py",
    "wizard/__init__.py",
    "wizard/post_call_wizard.py",
    "security/security.xml",
    "security/ir.model.access.csv",
    "security/rules.xml",
    "data/mail_templates.xml",
    "data/calendar_alarm_data.xml",
    "views/post_call_wizard_views.xml",
    "views/call_followup_views.xml",
    "views/crm_lead_views.xml",
    "static/src/js/post_call_service.js",
    "static/src/scss/post_call.scss",
    "tests/__init__.py",
    "tests/test_call_followup.py",
    "README.md",
}

DISPOSABLE_TEST = ROOT / "scripts" / "test_odoo_crm_call_followup_disposable.sh"
PRODUCTION_OVERLAY = ROOT / "deploy" / "odoo" / "compose.crm-call-followup.yaml"
STAGING_OVERLAY = ROOT / "deploy" / "odoo" / "compose.crm-call-followup.staging.yaml"
RELEASE_RUNBOOK = ROOT / "docs" / "runbooks" / "ODOO_CRM_CALL_FOLLOWUP_RELEASE.md"


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    errors: list[str] = []

    for relative in sorted(REQUIRED_FILES):
        if not (MODULE / relative).is_file():
            fail(errors, f"missing required file: {relative}")

    if not DISPOSABLE_TEST.is_file():
        fail(errors, "missing disposable Odoo 19 install/upgrade/uninstall gate")
    for release_file in (PRODUCTION_OVERLAY, STAGING_OVERLAY, RELEASE_RUNBOOK):
        if not release_file.is_file():
            fail(errors, f"missing release authority: {release_file.relative_to(ROOT)}")

    for overlay in (PRODUCTION_OVERLAY, STAGING_OVERLAY):
        if overlay.is_file():
            overlay_source = overlay.read_text(encoding="utf-8")
            if "ODOO_CRM_CALL_FOLLOWUP_ADDON_RELEASE:?" not in overlay_source:
                fail(errors, f"release overlay is not fail-closed: {overlay.name}")
            if ":/mnt/crm-call-followup-addons/codestra_crm_call_followup:ro" not in overlay_source:
                fail(errors, f"release overlay does not mount the addon read-only: {overlay.name}")

    if MANIFEST.is_file():
        try:
            manifest = ast.literal_eval(MANIFEST.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError) as exc:
            fail(errors, f"manifest is not a literal dictionary: {exc}")
            manifest = {}

        if not str(manifest.get("version", "")).startswith("19.0."):
            fail(errors, "manifest version must target Odoo 19")
        required_dependencies = {"crm", "calendar", "mail", "bus", "web"}
        missing_dependencies = required_dependencies - set(manifest.get("depends", []))
        if missing_dependencies:
            fail(errors, f"manifest missing dependencies: {sorted(missing_dependencies)}")
        for data_file in manifest.get("data", []):
            if not (MODULE / data_file).is_file():
                fail(errors, f"manifest data file does not exist: {data_file}")
        for asset_files in manifest.get("assets", {}).values():
            for asset in asset_files:
                prefix = "codestra_crm_call_followup/"
                relative = asset[len(prefix) :] if asset.startswith(prefix) else asset
                if not (MODULE / relative).is_file():
                    fail(errors, f"manifest asset does not exist: {asset}")

    for python_file in MODULE.rglob("*.py"):
        try:
            ast.parse(python_file.read_text(encoding="utf-8"), filename=str(python_file))
        except SyntaxError as exc:
            fail(errors, f"python syntax error in {python_file.relative_to(ROOT)}: {exc}")

    for xml_file in MODULE.rglob("*.xml"):
        try:
            ET.parse(xml_file)
        except ET.ParseError as exc:
            fail(errors, f"XML parse error in {xml_file.relative_to(ROOT)}: {exc}")

    view_source = (MODULE / "views" / "call_followup_views.xml").read_text(
        encoding="utf-8"
    )
    if 'default_period="today"' in view_source:
        fail(errors, "Odoo 19 does not accept today as a date-filter default_period")
    if '<group expand="' in view_source:
        fail(errors, "Odoo 19 search-view groups do not accept the expand attribute")
    if "('ended_at', '&gt;=', 'today')" not in view_source or "('ended_at', '&lt;', 'today +1d')" not in view_source:
        fail(errors, "Calls Today must use the Odoo 19 relative-date domain")

    python_and_js = "\n".join(
        path.read_text(encoding="utf-8")
        for pattern in ("*.py", "*.js")
        for path in MODULE.rglob(pattern)
    ).lower()
    for forbidden in (
        "auth=\"public\"",
        "auth='public'",
        "requests.post(",
        "requests.put(",
        "requests.patch(",
        "requests.delete(",
        "vicidial/admin.php",
        "vicidial/non_agent_api.php",
    ):
        if forbidden in python_and_js:
            fail(errors, f"forbidden direct or unauthenticated integration pattern: {forbidden}")

    model_source = (MODULE / "models" / "call_followup.py").read_text(
        encoding="utf-8"
    ) if (MODULE / "models" / "call_followup.py").is_file() else ""
    for required_snippet in (
        "group_call_followup_service",
        "UNIQUE(company_id, event_id)",
        "savepoint()",
        "IntegrityError",
        "_sendone",
        "get_pending_post_call_actions",
    ):
        if required_snippet not in model_source:
            fail(errors, f"completed-call model missing invariant: {required_snippet}")

    alarm_source = (MODULE / "data" / "calendar_alarm_data.xml").read_text(
        encoding="utf-8"
    ) if (MODULE / "data" / "calendar_alarm_data.xml").is_file() else ""
    for required_snippet in (
        "calendar_alarm_prepare_30_minutes",
        "<field name=\"duration\">30</field>",
        "calendar_alarm_email_15_minutes",
        "<field name=\"duration\">15</field>",
        "mail_template_callback_reminder_15",
    ):
        if required_snippet not in alarm_source:
            fail(errors, f"calendar reminder invariant missing: {required_snippet}")

    js_source = (MODULE / "static" / "src" / "js" / "post_call_service.js").read_text(
        encoding="utf-8"
    ) if (MODULE / "static" / "src" / "js" / "post_call_service.js").is_file() else ""
    for required_snippet in (
        "codestra_crm_call_followup.post_call",
        "bus_service.subscribe",
        "get_pending_post_call_actions",
        "codestra.crm.post.call.wizard",
    ):
        if required_snippet not in js_source:
            fail(errors, f"popup service invariant missing: {required_snippet}")

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_STATIC_GATE=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1

    print("ODOO_CRM_CALL_FOLLOWUP_STATIC_GATE=PASS")
    print(f"MODULE={MODULE.relative_to(ROOT)}")
    print("ODOO_TARGET=19")
    print("POST_CALL_POPUP=ENABLED_BY_AUTHENTICATED_EVENT")
    print("PREPARATION_POPUP_MINUTES=30")
    print("CLIENT_AGENT_EMAIL_MINUTES=15")
    return 0


if __name__ == "__main__":
    sys.exit(main())
