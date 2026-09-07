#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "odoo_addons" / "codestra_crm_call_followup_analytics"
REQUIRED = {
    "__init__.py",
    "__manifest__.py",
    "models/__init__.py",
    "models/report.py",
    "models/analytics_api.py",
    "security/ir.model.access.csv",
    "security/rules.xml",
    "views/analytics_views.xml",
    "tests/__init__.py",
    "tests/test_analytics.py",
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
            errors.append("analytics addon must depend on the core follow-up addon")
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

    source = "\n".join(path.read_text(encoding="utf-8") for path in MODULE.rglob("*.py"))
    for snippet in (
        "_auto = False",
        "CREATE VIEW",
        "drop_view_if_exists",
        "summary_v1",
        "agent_scorecards_v1",
        "pending_over_10_minutes",
        "email_failed",
    ):
        if snippet not in source:
            errors.append(f"missing analytics invariant: {snippet}")

    access_path = MODULE / "security" / "ir.model.access.csv"
    if access_path.is_file():
        for line in access_path.read_text(encoding="utf-8").splitlines()[1:]:
            columns = line.split(",")
            if len(columns) >= 8 and columns[-3:] != ["0", "0", "0"]:
                errors.append(f"analytics ACL is not read-only: {columns[0]}")

    lowered = source.lower()
    for forbidden in (
        "requests.post(",
        "requests.put(",
        "vicidial/admin.php",
        "vicidial/non_agent_api.php",
        "auth=\"public\"",
        "auth='public'",
    ):
        if forbidden in lowered:
            errors.append(f"forbidden integration pattern: {forbidden}")

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_ANALYTICS_GATE=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1
    print("ODOO_CRM_CALL_FOLLOWUP_ANALYTICS_GATE=PASS")
    print("REPORT_MODEL=READ_ONLY_SQL_VIEW")
    print("AGENT_SCOPE=ASSIGNED_ONLY")
    print("MANAGER_SCOPE=ALLOWED_COMPANIES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
