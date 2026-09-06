#!/usr/bin/env python3
"""Static gate for the optional CRM call follow-up delivery outbox addon."""

from __future__ import annotations

import ast
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "odoo_addons" / "codestra_crm_call_followup_delivery"
REQUIRED = {
    "__init__.py",
    "__manifest__.py",
    "README.md",
    "models/__init__.py",
    "models/delivery.py",
    "wizard/__init__.py",
    "wizard/post_call_wizard.py",
    "security/ir.model.access.csv",
    "security/rules.xml",
    "data/ir_cron_data.xml",
    "views/delivery_views.xml",
    "tests/__init__.py",
    "tests/test_delivery_outbox.py",
}


def main() -> int:
    errors: list[str] = []
    for relative in sorted(REQUIRED):
        if not (MODULE / relative).is_file():
            errors.append(f"missing required file: {relative}")

    for source in MODULE.rglob("*.py"):
        try:
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except SyntaxError as exc:
            errors.append(f"python syntax error in {source.relative_to(ROOT)}: {exc}")

    for source in MODULE.rglob("*.xml"):
        try:
            ET.parse(source)
        except ET.ParseError as exc:
            errors.append(f"XML parse error in {source.relative_to(ROOT)}: {exc}")

    acl_path = MODULE / "security" / "ir.model.access.csv"
    if acl_path.is_file():
        with acl_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            errors.append("delivery ACL file has no records")
        for row in rows:
            if row.get("perm_create") != "0" or row.get("perm_unlink") != "0":
                errors.append("delivery UI groups must not create or delete audit rows")

    model = (MODULE / "models" / "delivery.py").read_text(encoding="utf-8")
    for snippet in (
        "UNIQUE(idempotency_key)",
        "recipient_hash",
        "BACKOFF_MINUTES",
        "FOR UPDATE SKIP LOCKED",
        'flush_model(["state", "attempt_count", "max_attempts", "next_attempt_at"])',
        "_cron_reconcile_mail_states",
        "_cron_retry_failed",
        "action_retry_now",
        "action_cancel",
        'check_access("read")',
        "_prevent_delivery_deletion",
        '"auto_delete": False',
    ):
        if snippet not in model:
            errors.append(f"delivery model missing invariant: {snippet}")

    wizard = (MODULE / "wizard" / "post_call_wizard.py").read_text(encoding="utf-8")
    if "super()._queue_post_call_email" not in wizard:
        errors.append("delivery addon must preserve the native queued-mail workflow")
    if "enqueue_post_call_email" not in wizard:
        errors.append("post-call email must create a delivery ledger record")
    if '_inherit = "codestra.crm.post.call.wizard"' not in wizard:
        errors.append("delivery addon must inherit the installed post-call wizard model")

    cron = (MODULE / "data" / "ir_cron_data.xml").read_text(encoding="utf-8")
    for snippet in (
        "_cron_reconcile_mail_states",
        "_cron_retry_failed",
    ):
        if snippet not in cron:
            errors.append(f"delivery cron data missing: {snippet}")

    views = (MODULE / "views" / "delivery_views.xml").read_text(encoding="utf-8")
    for snippet in (
        "Retry Now",
        "Cancel Delivery",
        "Open Call Follow-up",
        "Open Odoo Mail",
        "Dead Letter",
    ):
        if snippet not in views:
            errors.append(f"delivery operations view missing CTA: {snippet}")

    governed_suffixes = {".py", ".xml", ".csv", ".md"}
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in MODULE.rglob("*")
        if path.is_file() and path.suffix in governed_suffixes
    )
    for forbidden in (
        "requests.post(",
        "smtplib",
        "auth=\"public\"",
        "vicidial/non_agent_api.php",
    ):
        if forbidden in combined.lower():
            errors.append(f"forbidden delivery integration pattern: {forbidden}")

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_DELIVERY_GATE=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1

    print("ODOO_CRM_CALL_FOLLOWUP_DELIVERY_GATE=PASS")
    print("NATIVE_ODOO_MAIL_QUEUE=PRESERVED")
    print("DELIVERY_IDEMPOTENCY=ENABLED")
    print("DEAD_LETTER_STATE=ENABLED")
    print("MAX_ATTEMPTS=5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
