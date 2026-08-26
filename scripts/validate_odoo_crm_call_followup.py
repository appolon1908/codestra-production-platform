#!/usr/bin/env python3
"""Static release gate for the Codestra Odoo 19 CRM call follow-up addon."""

from __future__ import annotations

import ast
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "odoo_addons" / "codestra_crm_call_followup"
MANIFEST = MODULE / "__manifest__.py"

REQUIRED_MODULE_FILES = {
    "__init__.py",
    "__manifest__.py",
    "README.md",
    "models/__init__.py",
    "models/call_followup.py",
    "models/call_followup_api.py",
    "models/calendar_event.py",
    "models/crm_lead.py",
    "wizard/__init__.py",
    "wizard/post_call_wizard.py",
    "security/security.xml",
    "security/ir.model.access.csv",
    "security/rules.xml",
    "contracts/completed_call.v1.schema.json",
    "contracts/completed_call.response.v1.schema.json",
    "data/mail_templates.xml",
    "data/calendar_alarm_data.xml",
    "views/post_call_wizard_views.xml",
    "views/call_followup_views.xml",
    "views/crm_lead_views.xml",
    "static/src/js/post_call_service.js",
    "static/src/scss/post_call.scss",
    "tests/__init__.py",
    "tests/test_call_followup.py",
}

REQUIRED_REPOSITORY_FILES = {
    "scripts/test_odoo_crm_call_followup_disposable.sh",
    "deploy/odoo/compose.crm-call-followup.yaml",
    "deploy/odoo/compose.crm-call-followup.staging.yaml",
    "docs/runbooks/ODOO_CRM_CALL_FOLLOWUP_RELEASE.md",
    "docs/api/ODOO_CRM_CALL_FOLLOWUP_API_V1.md",
    "docs/architecture/ODOO_CRM_CALL_FOLLOWUP_BRANCH_MAP.md",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def require_snippets(
    errors: list[str],
    source: str,
    snippets: tuple[str, ...],
    label: str,
) -> None:
    for snippet in snippets:
        if snippet not in source:
            fail(errors, f"{label} missing invariant: {snippet}")


def main() -> int:
    errors: list[str] = []

    for relative in sorted(REQUIRED_MODULE_FILES):
        if not (MODULE / relative).is_file():
            fail(errors, f"missing required module file: {relative}")

    for relative in sorted(REQUIRED_REPOSITORY_FILES):
        if not (ROOT / relative).is_file():
            fail(errors, f"missing required repository file: {relative}")

    if MANIFEST.is_file():
        try:
            manifest = ast.literal_eval(MANIFEST.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError) as exc:
            fail(errors, f"manifest is not a literal dictionary: {exc}")
            manifest = {}

        version = str(manifest.get("version", ""))
        if not version.startswith("19.0."):
            fail(errors, "manifest version must target Odoo 19")
        if version < "19.0.2.0.0":
            fail(errors, "manifest version must include the API/UX hardening release")

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
                relative = asset[len(prefix):] if asset.startswith(prefix) else asset
                if not (MODULE / relative).is_file():
                    fail(errors, f"manifest asset does not exist: {asset}")

    for python_file in MODULE.rglob("*.py"):
        try:
            ast.parse(
                python_file.read_text(encoding="utf-8"),
                filename=str(python_file),
            )
        except SyntaxError as exc:
            fail(
                errors,
                f"python syntax error in {python_file.relative_to(ROOT)}: {exc}",
            )

    for python_file in (ROOT / "scripts").glob("*crm_call_followup*.py"):
        try:
            ast.parse(
                python_file.read_text(encoding="utf-8"),
                filename=str(python_file),
            )
        except SyntaxError as exc:
            fail(
                errors,
                f"python syntax error in {python_file.relative_to(ROOT)}: {exc}",
            )

    for xml_file in MODULE.rglob("*.xml"):
        try:
            ET.parse(xml_file)
        except ET.ParseError as exc:
            fail(
                errors,
                f"XML parse error in {xml_file.relative_to(ROOT)}: {exc}",
            )

    schema_paths = [
        MODULE / "contracts" / "completed_call.v1.schema.json",
        MODULE / "contracts" / "completed_call.response.v1.schema.json",
    ]
    schemas = []
    for schema_path in schema_paths:
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schemas.append(schema)
        except (OSError, json.JSONDecodeError) as exc:
            fail(
                errors,
                f"invalid JSON schema {schema_path.relative_to(ROOT)}: {exc}",
            )
    if schemas:
        request_schema = schemas[0]
        if request_schema.get("additionalProperties") is not False:
            fail(errors, "request schema must reject unknown top-level fields")
        required = set(request_schema.get("required", []))
        for field in {"api_version", "event_id", "company_id", "ended_at"}:
            if field not in required:
                fail(errors, f"request schema missing required field: {field}")

    for overlay_name in (
        "deploy/odoo/compose.crm-call-followup.yaml",
        "deploy/odoo/compose.crm-call-followup.staging.yaml",
    ):
        overlay_path = ROOT / overlay_name
        if not overlay_path.is_file():
            continue
        overlay_source = overlay_path.read_text(encoding="utf-8")
        if "ODOO_CRM_CALL_FOLLOWUP_ADDON_RELEASE:?" not in overlay_source:
            fail(errors, f"release overlay is not fail-closed: {overlay_name}")
        if (
            ":/mnt/crm-call-followup-addons/"
            "codestra_crm_call_followup:ro"
        ) not in overlay_source:
            fail(errors, f"release overlay does not mount addon read-only: {overlay_name}")

    staging_overlay = ROOT / "deploy/odoo/compose.crm-call-followup.staging.yaml"
    if staging_overlay.is_file():
        staging_source = staging_overlay.read_text(encoding="utf-8")
        if "ODOO_CALL_CENTER_ADDON_RELEASE:?" not in staging_source:
            fail(errors, "staging overlay does not fail closed on call-center parity")
        if ":/mnt/call-center-addons/call_center_campaign:ro" not in staging_source:
            fail(errors, "staging overlay does not pin call_center_campaign read-only")

    combined_python_js = "\n".join(
        path.read_text(encoding="utf-8")
        for pattern in ("*.py", "*.js")
        for path in MODULE.rglob(pattern)
    ).lower()
    for forbidden in (
        'auth="public"',
        "auth='public'",
        "requests.post(",
        "requests.put(",
        "requests.patch(",
        "requests.delete(",
        "vicidial/admin.php",
        "vicidial/non_agent_api.php",
    ):
        if forbidden in combined_python_js:
            fail(errors, f"forbidden integration pattern: {forbidden}")

    model_source = (
        (MODULE / "models" / "call_followup.py").read_text(encoding="utf-8")
        if (MODULE / "models" / "call_followup.py").is_file()
        else ""
    )
    require_snippets(
        errors,
        model_source,
        (
            "UNIQUE(company_id, event_id)",
            "request_fingerprint",
            "IDEMPOTENCY_CONFLICT",
            "FOR UPDATE",
            "snoozed_until",
            "completed_by_id",
            "_prevent_audit_deletion",
            "get_pending_post_call_actions",
        ),
        "completed-call model",
    )

    api_source = (
        (MODULE / "models" / "call_followup_api.py").read_text(encoding="utf-8")
        if (MODULE / "models" / "call_followup_api.py").is_file()
        else ""
    )
    require_snippets(
        errors,
        api_source,
        (
            "API_VERSION",
            "MAX_PAYLOAD_BYTES",
            "ALLOWED_PAYLOAD_FIELDS",
            "UNKNOWN_PAYLOAD_FIELDS",
            "UNSUPPORTED_API_VERSION",
            "group_call_followup_service",
            "savepoint()",
            "IntegrityError",
            "_sendone",
            "register_completed_call",
            "get_contract",
            "health",
        ),
        "versioned API model",
    )

    wizard_source = (
        (MODULE / "wizard" / "post_call_wizard.py").read_text(encoding="utf-8")
        if (MODULE / "wizard" / "post_call_wizard.py").is_file()
        else ""
    )
    require_snippets(
        errors,
        wizard_source,
        (
            "_lock_for_completion",
            "action_snooze_10_minutes",
            "action_open_related_record",
            '"privacy": "private"',
            "compliance_review_required",
            "customer_sentiment",
            "contact_channel",
        ),
        "post-call wizard",
    )

    view_source = (
        (MODULE / "views" / "call_followup_views.xml").read_text(encoding="utf-8")
        if (MODULE / "views" / "call_followup_views.xml").is_file()
        else ""
    )
    if 'default_period="today"' in view_source:
        fail(errors, "Odoo 19 does not accept today as a date-filter default_period")
    if '<group expand="' in view_source:
        fail(errors, "Odoo 19 search-view groups do not accept expand")
    has_relative_today = (
        "('ended_at', '&gt;=', 'today')" in view_source
        and "('ended_at', '&lt;', 'today +1d')" in view_source
    )
    if 'date="ended_at"' not in view_source and not has_relative_today:
        fail(errors, "call history must expose a compatible date filter")
    if '<field name="calendar_event_id" column_invisible="True"/>' not in view_source:
        fail(errors, "list calendar CTA must declare hidden calendar_event_id")

    wizard_view = (
        (MODULE / "views" / "post_call_wizard_views.xml").read_text(encoding="utf-8")
        if (MODULE / "views" / "post_call_wizard_views.xml").is_file()
        else ""
    )
    require_snippets(
        errors,
        wizard_view,
        (
            "Save &amp; Complete",
            "Save &amp; Schedule",
            "Complete Without Email",
            "Save &amp; Remind Me in 10 Minutes",
            "Open CRM",
        ),
        "post-call CTA view",
    )

    alarm_source = (
        (MODULE / "data" / "calendar_alarm_data.xml").read_text(encoding="utf-8")
        if (MODULE / "data" / "calendar_alarm_data.xml").is_file()
        else ""
    )
    require_snippets(
        errors,
        alarm_source,
        (
            "calendar_alarm_prepare_30_minutes",
            '<field name="duration">30</field>',
            "calendar_alarm_email_15_minutes",
            '<field name="duration">15</field>',
            "mail_template_callback_reminder_15",
        ),
        "calendar reminder data",
    )

    js_source = (
        (MODULE / "static" / "src" / "js" / "post_call_service.js").read_text(
            encoding="utf-8"
        )
        if (MODULE / "static" / "src" / "js" / "post_call_service.js").is_file()
        else ""
    )
    require_snippets(
        errors,
        js_source,
        (
            "codestra_crm_call_followup.post_call",
            "bus_service.subscribe",
            "bus_service.start",
            "get_pending_post_call_actions",
            "Open Call Follow-ups",
        ),
        "popup service",
    )

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_STATIC_GATE=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1

    print("ODOO_CRM_CALL_FOLLOWUP_STATIC_GATE=PASS")
    print(f"MODULE={MODULE.relative_to(ROOT)}")
    print("ODOO_TARGET=19")
    print("API_VERSION=1.0")
    print("IDEMPOTENCY_CONFLICT_CHECK=ENABLED")
    print("DOUBLE_SUBMIT_LOCK=ENABLED")
    print("POST_CALL_POPUP=ENABLED_BY_AUTHENTICATED_EVENT")
    print("PREPARATION_POPUP_MINUTES=30")
    print("CLIENT_AGENT_EMAIL_MINUTES=15")
    return 0


if __name__ == "__main__":
    sys.exit(main())
