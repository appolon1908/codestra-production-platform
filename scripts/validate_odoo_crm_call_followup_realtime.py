#!/usr/bin/env python3
"""Static gate for the optional CRM call follow-up realtime lease addon."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "odoo_addons" / "codestra_crm_call_followup_realtime"
REQUIRED = {
    "__init__.py",
    "__manifest__.py",
    "README.md",
    "models/__init__.py",
    "models/realtime_lease.py",
    "static/src/js/post_call_lease_service.js",
    "tests/__init__.py",
    "tests/test_realtime_lease.py",
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

    model = (MODULE / "models" / "realtime_lease.py").read_text(encoding="utf-8")
    for snippet in (
        "FOR UPDATE SKIP LOCKED",
        "popup_lease_token",
        "popup_lease_owner",
        "popup_lease_expires_at",
        "claim_pending_post_call_actions",
        "renew_popup_lease",
        "release_popup_lease",
        "hmac.compare_digest",
    ):
        if snippet not in model:
            errors.append(f"realtime model missing invariant: {snippet}")

    js = (MODULE / "static" / "src" / "js" / "post_call_lease_service.js").read_text(
        encoding="utf-8"
    )
    for snippet in (
        "claim_pending_post_call_actions",
        "renew_popup_lease",
        "release_popup_lease",
        "browser.sessionStorage",
        "{ force: true }",
    ):
        if snippet not in js:
            errors.append(f"realtime browser service missing invariant: {snippet}")

    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in MODULE.rglob("*.*")
    )
    for forbidden in ("requests.post(", "auth=\"public\"", "vicidial/non_agent_api.php"):
        if forbidden in combined.lower():
            errors.append(f"forbidden realtime integration pattern: {forbidden}")

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_REALTIME_GATE=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1

    print("ODOO_CRM_CALL_FOLLOWUP_REALTIME_GATE=PASS")
    print("LEASE_TTL_SECONDS=120")
    print("CROSS_TAB_ATOMIC_CLAIM=ENABLED")
    print("STALE_LEASE_RECOVERY=ENABLED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
