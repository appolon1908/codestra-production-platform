#!/usr/bin/env python3
"""Validate the consolidated Odoo call-followup extension set."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VALIDATORS = (
    "scripts/validate_odoo_crm_call_followup.py",
    "scripts/validate_odoo_crm_call_followup_api.py",
    "scripts/validate_odoo_crm_call_followup_ux.py",
    "scripts/validate_odoo_crm_call_followup_automation.py",
)
REQUIRED_PATHS = (
    "odoo_addons/codestra_crm_call_followup_api/models/hardening.py",
    "odoo_addons/codestra_crm_call_followup_api/tests/test_hardening.py",
    "odoo_addons/codestra_crm_call_followup_ux/models/hardening.py",
    "odoo_addons/codestra_crm_call_followup_ux/tests/test_hardening.py",
    "odoo_addons/codestra_crm_call_followup_automation/models/hardening.py",
    "odoo_addons/codestra_crm_call_followup_automation/tests/test_hardening.py",
    "scripts/test_odoo_crm_call_followup_extensions_disposable.sh",
    "config/draft-pr-disposition-2026-09-02.json",
    "docs/governance/DRAFT_PR_REVIEW_2026-09-02.md",
    "REPOSITORY_PROFILE.md",
)
EXPECTED_DRAFTS = {
    5, 6, 7, 8, 9, 16, 17, 115, 119, 120, 121,
    122, 123, 124, 125, 126, 128, 131, 135, 151, 155,
}


def main() -> int:
    errors: list[str] = []

    for relative in REQUIRED_PATHS:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing consolidated authority: {relative}")

    for relative in VALIDATORS:
        completed = subprocess.run(
            [sys.executable, str(ROOT / relative)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            errors.append(
                f"{relative} failed: "
                f"{completed.stdout.strip()} {completed.stderr.strip()}"
            )

    for addon in (
        "codestra_crm_call_followup_api",
        "codestra_crm_call_followup_ux",
        "codestra_crm_call_followup_automation",
    ):
        addon_root = ROOT / "odoo_addons" / addon
        for path in addon_root.rglob("*.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                errors.append(
                    f"python syntax error in {path.relative_to(ROOT)}: {exc}"
                )

    api_source = (
        ROOT
        / "odoo_addons/codestra_crm_call_followup_api/models/hardening.py"
    ).read_text(encoding="utf-8")
    for token in (
        "MAX_PAYLOAD_BYTES = 65_536",
        "Unsupported completed-call API version",
        "email_split",
        "max_payload_bytes",
    ):
        if token not in api_source:
            errors.append(f"API hardening missing invariant: {token}")

    client_source = (
        ROOT / "integrations/odoo_call_followup_client.py"
    ).read_text(encoding="utf-8")
    for token in (
        "field(repr=False)",
        'parsed.scheme != "https"',
        "parsed.username",
        "parsed.password",
        "max_attempts must be between 1 and 10",
    ):
        if token not in client_source:
            errors.append(f"reference client missing invariant: {token}")

    ux_source = (
        ROOT
        / "odoo_addons/codestra_crm_call_followup_ux/models/hardening.py"
    ).read_text(encoding="utf-8")
    if "FOR UPDATE SKIP LOCKED" not in ux_source:
        errors.append("UX snooze release is not lease-safe")

    automation_source = (
        ROOT
        / "odoo_addons/codestra_crm_call_followup_automation/models/hardening.py"
    ).read_text(encoding="utf-8")
    for token in (
        "O_NOFOLLOW",
        "O_NONBLOCK",
        "os.fstat",
        "stat.S_ISREG",
        "parsed.query",
    ):
        if token not in automation_source:
            errors.append(
                f"automation secret hardening missing invariant: {token}"
            )

    disposition_path = (
        ROOT / "config/draft-pr-disposition-2026-09-02.json"
    )
    try:
        disposition = json.loads(
            disposition_path.read_text(encoding="utf-8")
        )
        observed = {
            int(entry["pullRequest"])
            for entry in disposition.get("drafts", [])
        }
        if observed != EXPECTED_DRAFTS:
            errors.append(
                "draft disposition does not cover the exact reviewed queue"
            )
        if disposition.get("allDraftsReviewed") is not True:
            errors.append("draft review is not marked complete")
        if disposition.get("runtimeMutation") is not False:
            errors.append("draft review must remain source-only")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"invalid draft disposition manifest: {exc}")

    if errors:
        print("CALL_FOLLOWUP_EXTENSION_CONSOLIDATION=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1

    print("CALL_FOLLOWUP_EXTENSION_CONSOLIDATION=PASS")
    print("DRAFTS_REVIEWED=21/21")
    print("PROMOTED_EXTENSIONS=API,UX,AUTOMATION")
    print("REMOTE_AUTOMATION_ENABLED=FALSE")
    print("PRODUCTION_DEPLOYED=NO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
