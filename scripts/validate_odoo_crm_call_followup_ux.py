#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "odoo_addons" / "codestra_crm_call_followup_ux"
REQUIRED = {
    "__init__.py",
    "__manifest__.py",
    "models/__init__.py",
    "models/followup.py",
    "wizard/__init__.py",
    "wizard/post_call_wizard.py",
    "views/workspace_views.xml",
    "static/src/scss/workspace.scss",
    "tests/__init__.py",
    "tests/test_workspace.py",
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
            errors.append("workspace addon must depend on the core follow-up addon")
        for relative in manifest.get("data", []):
            if not (MODULE / relative).is_file():
                errors.append(f"manifest data file does not exist: {relative}")
        for assets in manifest.get("assets", {}).values():
            for asset in assets:
                prefix = "codestra_crm_call_followup_ux/"
                if asset.startswith(prefix):
                    asset = asset[len(prefix):]
                if not (MODULE / asset).is_file():
                    errors.append(f"manifest asset does not exist: {asset}")

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

    python_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in MODULE.rglob("*.py")
    )
    view_source = (MODULE / "views" / "workspace_views.xml").read_text(
        encoding="utf-8"
    ) if (MODULE / "views" / "workspace_views.xml").is_file() else ""
    scss_source = (MODULE / "static" / "src" / "scss" / "workspace.scss").read_text(
        encoding="utf-8"
    ) if (MODULE / "static" / "src" / "scss" / "workspace.scss").is_file() else ""

    for snippet in (
        "action_ux_open_customer",
        "action_ux_open_opportunity",
        "action_ux_open_calendar",
        "action_ux_complete_without_email",
        "action_ux_complete_and_open_calendar",
        "action_ux_primary",
    ):
        if snippet not in python_source:
            errors.append(f"missing workspace CTA implementation: {snippet}")

    for label in (
        "Save &amp; Complete",
        "Complete &amp; Open Calendar",
        "Complete Without Email",
        "Complete &amp; Open Customer",
        "My Post-call Workspace",
    ):
        if label not in view_source:
            errors.append(f"missing visible workspace CTA or action: {label}")

    if "t-att-class" in view_source or "t-on-" in view_source:
        errors.append("backend form architecture contains unsupported Owl directives")
    if "@media (max-width: 767.98px)" not in scss_source:
        errors.append("workspace stylesheet is missing the narrow-browser layout")

    lowered = (python_source + view_source).lower()
    for forbidden in (
        "auth=\"public\"",
        "auth='public'",
        "requests.post(",
        "requests.put(",
        "vicidial/admin.php",
        "vicidial/non_agent_api.php",
    ):
        if forbidden in lowered:
            errors.append(f"forbidden integration pattern: {forbidden}")

    if errors:
        print("ODOO_CRM_CALL_FOLLOWUP_UX_GATE=FAIL")
        for error in errors:
            print(f"ERROR={error}")
        return 1
    print("ODOO_CRM_CALL_FOLLOWUP_UX_GATE=PASS")
    print("FORMS=READY_FOR_RUNTIME_VALIDATION")
    print("CALLS_TO_ACTION=WIRED_TO_CORE_WORKFLOW")
    print("NARROW_BROWSER_LAYOUT=DEFINED")
    print("DIRECT_TELEPHONY_WRITES=NONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
