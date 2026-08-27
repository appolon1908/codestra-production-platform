#!/usr/bin/env python3
"""Fail-closed static release gate for the Odoo 19 call follow-up addon."""

from __future__ import annotations

import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "odoo_addons" / "codestra_crm_call_followup"
MANIFEST = MODULE / "__manifest__.py"
WORKFLOW = ROOT / ".github" / "workflows" / "odoo-crm-call-followup.yml"

REQUIRED_FILES = {
    "__init__.py",
    "__manifest__.py",
    "models/__init__.py",
    "models/call_followup.py",
    "models/call_followup_hardening.py",
    "models/delivery_intent.py",
    "models/calendar_event.py",
    "models/crm_lead.py",
    "wizard/__init__.py",
    "wizard/post_call_wizard.py",
    "wizard/post_call_wizard_hardening.py",
    "security/security.xml",
    "security/ir.model.access.csv",
    "security/rules.xml",
    "data/mail_templates.xml",
    "data/calendar_alarm_data.xml",
    "views/post_call_wizard_views.xml",
    "views/call_followup_views.xml",
    "views/delivery_intent_views.xml",
    "views/crm_lead_views.xml",
    "static/src/js/post_call_service.js",
    "static/src/scss/post_call.scss",
    "tests/__init__.py",
    "tests/test_call_followup.py",
    "tests/test_call_followup_hardening.py",
    "migrations/19.0.1.2.0/post-migrate.py",
    "README.md",
}

DISPOSABLE_TEST = ROOT / "scripts" / "test_odoo_crm_call_followup_disposable.sh"
PRODUCTION_OVERLAY = ROOT / "deploy" / "odoo" / "compose.crm-call-followup.yaml"
STAGING_OVERLAY = ROOT / "deploy" / "odoo" / "compose.crm-call-followup.staging.yaml"
RELEASE_RUNBOOK = ROOT / "docs" / "runbooks" / "ODOO_CRM_CALL_FOLLOWUP_RELEASE.md"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ACTION_REF = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def require_snippets(
    errors: list[str], source: str, snippets: tuple[str, ...], label: str
) -> None:
    for snippet in snippets:
        require(errors, snippet in source, f"{label} missing invariant: {snippet}")


def validate_workflow(errors: list[str]) -> None:
    require(errors, WORKFLOW.is_file(), "missing dedicated GitHub Actions workflow")
    if not WORKFLOW.is_file():
        return
    source = read(WORKFLOW)
    require(errors, "runs-on: ubuntu-24.04" in source, "workflow runner is not pinned")
    require_snippets(
        errors,
        source,
        (
            "Validate exact Odoo call-follow-up source head",
            "Validate Odoo call-follow-up merge result",
            "github.event.pull_request.head.sha",
            'test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"',
            "persist-credentials: false",
        ),
        "workflow",
    )
    for action in ACTION_REF.findall(source):
        if action.startswith("./") or action.startswith("docker://"):
            continue
        require(
            errors,
            "@" in action and FULL_SHA.fullmatch(action.rsplit("@", 1)[1]) is not None,
            f"workflow action is not pinned to a 40-character SHA: {action}",
        )


def main() -> int:
    errors: list[str] = []

    for relative in sorted(REQUIRED_FILES):
        require(errors, (MODULE / relative).is_file(), f"missing required file: {relative}")
    require(errors, DISPOSABLE_TEST.is_file(), "missing disposable runtime gate")
    for release_file in (PRODUCTION_OVERLAY, STAGING_OVERLAY, RELEASE_RUNBOOK):
        require(
            errors,
            release_file.is_file(),
            f"missing release authority: {release_file.relative_to(ROOT)}",
        )

    for overlay in (PRODUCTION_OVERLAY, STAGING_OVERLAY):
        if not overlay.is_file():
            continue
        overlay_source = read(overlay)
        require(
            errors,
            "ODOO_CRM_CALL_FOLLOWUP_ADDON_RELEASE:?" in overlay_source,
            f"release overlay is not fail-closed: {overlay.name}",
        )
        require(
            errors,
            ":/mnt/crm-call-followup-addons/codestra_crm_call_followup:ro"
            in overlay_source,
            f"release overlay does not mount addon read-only: {overlay.name}",
        )

    if STAGING_OVERLAY.is_file():
        staging = read(STAGING_OVERLAY)
        for snippet, message in (
            (
                "ODOO_CRM_CALL_FOLLOWUP_STAGING_MAIL_INBOX_RELEASE:?",
                "staging overlay does not pin the mail inbox dependency",
            ),
            (
                ":/mnt/staging-mail-inbox-addons/codestra_mail_inbox:ro",
                "staging overlay does not mount mail inbox read-only",
            ),
            (
                "ODOO_CALL_CENTER_ADDON_RELEASE:?",
                "staging overlay does not pin call-center source parity",
            ),
        ):
            require(errors, snippet in staging, message)

    manifest: dict[str, object] = {}
    if MANIFEST.is_file():
        try:
            value = ast.literal_eval(read(MANIFEST))
            require(errors, isinstance(value, dict), "manifest root must be a dictionary")
            if isinstance(value, dict):
                manifest = value
        except (SyntaxError, ValueError) as exc:
            errors.append(f"manifest is not a literal dictionary: {exc}")
    require(
        errors,
        manifest.get("version") == "19.0.1.2.0",
        "manifest version must be exactly 19.0.1.2.0",
    )
    required_dependencies = {"crm", "calendar", "mail", "bus", "web"}
    require(
        errors,
        required_dependencies.issubset(set(manifest.get("depends", []))),
        "manifest is missing required Odoo dependencies",
    )
    for data_file in manifest.get("data", []):
        require(errors, (MODULE / data_file).is_file(), f"missing data file: {data_file}")
    for asset_files in manifest.get("assets", {}).values():
        for asset in asset_files:
            prefix = "codestra_crm_call_followup/"
            relative = asset[len(prefix) :] if asset.startswith(prefix) else asset
            require(errors, (MODULE / relative).is_file(), f"missing asset: {asset}")

    for python_file in MODULE.rglob("*.py"):
        try:
            ast.parse(read(python_file), filename=str(python_file))
        except SyntaxError as exc:
            errors.append(f"python syntax error in {python_file.relative_to(ROOT)}: {exc}")
    for xml_file in MODULE.rglob("*.xml"):
        try:
            ET.parse(xml_file)
        except ET.ParseError as exc:
            errors.append(f"XML parse error in {xml_file.relative_to(ROOT)}: {exc}")

    combined = "\n".join(
        read(path)
        for pattern in ("*.py", "*.js", "*.xml")
        for path in MODULE.rglob(pattern)
    )
    lowered = combined.lower()
    for forbidden in (
        "auth=\"public\"",
        "auth='public'",
        "requests.post(",
        "requests.put(",
        "requests.patch(",
        "requests.delete(",
        "vicidial/admin.php",
        "vicidial/non_agent_api.php",
        ".send_mail(",
        "force_send=true",
        '<field name="alarm_type">email</field>',
    ):
        require(
            errors,
            forbidden not in lowered,
            f"forbidden direct or unauthenticated effect remains: {forbidden}",
        )

    model_source = read(MODULE / "models" / "call_followup.py")
    require_snippets(
        errors,
        model_source,
        (
            "group_call_followup_service",
            "UNIQUE(company_id, event_id)",
            "savepoint()",
            "IntegrityError",
            "_sendone",
        ),
        "completed-call model",
    )

    hardening = read(MODULE / "models" / "call_followup_hardening.py")
    require_snippets(
        errors,
        hardening,
        (
            "company_id is required",
            "group_call_followup_user",
            "submitted_customer_name",
            "submitted_customer_email",
            "payload.get(\"partner_id\")",
            "after_ended_at",
            "after_id",
            "_workflow_only_fields",
        ),
        "registration hardening",
    )

    delivery = read(MODULE / "models" / "delivery_intent.py")
    require_snippets(
        errors,
        delivery,
        (
            'Only the authenticated Middleware service may claim',
            "UNIQUE(company_id, idempotency_key)",
            "FOR UPDATE SKIP LOCKED",
            "claim_due_delivery_intents",
            "acknowledge_delivery_intent",
            "release_or_dead_letter_delivery_intent",
            "requires_consent_check",
            "_sync_reminder_delivery_intents",
        ),
        "Middleware delivery outbox",
    )

    wizard = read(MODULE / "wizard" / "post_call_wizard.py")
    require_snippets(
        errors,
        wizard,
        (
            "_claim_pending_followup",
            "state = 'pending' FOR UPDATE",
            "_create_delivery_intent",
            "no_mail_to_attendees",
            "immediate_delivery_intent_id",
            "_sync_reminder_delivery_intents",
            "Command.set([followup.agent_id.partner_id.id])",
        ),
        "post-call workflow",
    )

    calendar_source = read(MODULE / "models" / "calendar_event.py")
    require_snippets(
        errors,
        calendar_source,
        (
            "_codestra_linked_events",
            "no_mail_to_attendees=True",
            "not preserved_kind",
            "_sync_reminder_delivery_intents",
        ),
        "calendar synchronization",
    )

    alarm_source = read(MODULE / "data" / "calendar_alarm_data.xml")
    require_snippets(
        errors,
        alarm_source,
        (
            "calendar_alarm_prepare_30_minutes",
            '<field name="alarm_type">notification</field>',
            '<field name="duration">30</field>',
        ),
        "internal calendar alarm",
    )
    require(
        errors,
        '<field name="alarm_type">email</field>' not in alarm_source.lower(),
        "calendar alarm data still declares a direct email alarm",
    )
    require(
        errors,
        "calendar_alarm_email_15_minutes" not in alarm_source,
        "legacy direct-email calendar alarm remains in install data",
    )

    js_source = read(MODULE / "static" / "src" / "js" / "post_call_service.js")
    require_snippets(
        errors,
        js_source,
        (
            "scheduleWakeup",
            "snoozed_until",
            "after_ended_at",
            "after_id",
            "RECOVERY_POLL_MS",
            "queuedOrOpen",
        ),
        "browser recovery service",
    )
    for obsolete in ("seenFollowups", "exclude_ids: Array.from"):
        require(errors, obsolete not in js_source, f"obsolete popup pagination remains: {obsolete}")

    migration = read(MODULE / "migrations" / "19.0.1.2.0" / "post-migrate.py")
    require_snippets(
        errors,
        migration,
        (
            "not event.codestra_schedule_kind",
            "no_mail_to_attendees=True",
            "Command.set(agent_partner.ids)",
            '("mail_id.state", "in", ["outgoing", "exception"])',
            'legacy_mail.write({"state": "cancel"})',
            '"immediate_delivery_intent_id": intent.id',
            "_sync_reminder_delivery_intents",
        ),
        "upgrade migration",
    )

    tests = read(MODULE / "tests" / "test_call_followup.py") + read(
        MODULE / "tests" / "test_call_followup_hardening.py"
    )
    require_snippets(
        errors,
        tests,
        (
            "test_company_is_required",
            "test_selected_agent_must_have_call_followup_privilege",
            "test_fallback_customer_identity_is_part_of_replay_fingerprint",
            "test_exact_lead_only_replay_survives_later_partner_change",
            "test_pending_cursor_reaches_more_than_220_records",
            "test_immediate_email_records_intent_without_creating_mail",
            "test_middleware_service_claims_and_acknowledges_intent",
            "test_manager_cannot_bypass_workflow_with_direct_state_write",
        ),
        "regression suite",
    )

    validate_workflow(errors)

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_STATIC_GATE=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1

    print("ODOO_CRM_CALL_FOLLOWUP_STATIC_GATE=PASS")
    print(f"MODULE={MODULE.relative_to(ROOT)}")
    print("ODOO_TARGET=19")
    print("MIDDLEWARE_SOLE_EXTERNAL_DELIVERY_BOUNDARY=PASS")
    print("NATIVE_ODOO_ATTENDEE_EMAIL=DISALLOWED")
    print("REPLAY_FINGERPRINT_REQUEST_DERIVED=PASS")
    print("PENDING_CURSOR_STABLE=PASS")
    print("SNOOZE_WAKEUP_TIMER=PASS")
    print("UPGRADE_BACKFILL=REQUIRED_AND_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
