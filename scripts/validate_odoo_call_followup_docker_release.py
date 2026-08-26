#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "deploy" / "odoo" / "call-followup-release"
EXPECTED_INTEGRATION_SHA = "32ef97f27459cf57c58e7b329ab8ed0ae9c0f34d"
EXPECTED_MODULES = {
    "codestra_crm_call_followup",
    "codestra_crm_call_followup_api",
    "codestra_crm_call_followup_ux",
    "codestra_crm_call_followup_automation",
}


def main() -> int:
    errors: list[str] = []
    required = [
        PACKAGE / "Dockerfile",
        PACKAGE / "Dockerfile.dockerignore",
        PACKAGE / "healthcheck.py",
        PACKAGE / "release-manifest.json",
        PACKAGE / "compose.release.yaml",
        PACKAGE / "compose.install.yaml",
        PACKAGE / "compose.upgrade.yaml",
        PACKAGE / "compose.automation-secrets.yaml",
        PACKAGE / "build.sh",
        PACKAGE / "validate.sh",
        PACKAGE / "deploy.sh",
        PACKAGE / "ROLLBACK.md",
        PACKAGE / "README.md",
        ROOT / "docs" / "CODEX_ODOO19_CALL_FOLLOWUP_DOCKER_RELEASE.md",
        ROOT / ".github" / "workflows" / "odoo-call-followup-docker-release.yml",
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    try:
        ast.parse(
            (PACKAGE / "healthcheck.py").read_text(encoding="utf-8"),
            filename=str(PACKAGE / "healthcheck.py"),
        )
    except SyntaxError as exc:
        errors.append(f"healthcheck Python syntax error: {exc}")

    try:
        manifest = json.loads(
            (PACKAGE / "release-manifest.json").read_text(encoding="utf-8")
        )
        if manifest.get("integration_source_sha") != EXPECTED_INTEGRATION_SHA:
            errors.append("release manifest integration SHA is not locked")
        if set(manifest.get("modules", [])) != EXPECTED_MODULES:
            errors.append("release manifest module set is incomplete")
        defaults = manifest.get("runtime_defaults", {})
        if defaults.get("automation_remote_delivery_enabled") is not False:
            errors.append("automation must default to disabled")
        if defaults.get("direct_vicidial_writes") is not False:
            errors.append("direct VICIdial writes must remain disabled")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid release manifest: {exc}")

    dockerfile = (PACKAGE / "Dockerfile").read_text(encoding="utf-8")
    if "FROM ${ODOO_BASE_IMAGE}" not in dockerfile:
        errors.append("Dockerfile does not use the pinned base-image argument")
    if "ARG ODOO_BASE_IMAGE=odoo@sha256:" not in dockerfile:
        errors.append("Dockerfile base image is not digest pinned")
    if "\nUSER odoo\n" not in dockerfile:
        errors.append("Dockerfile does not finish with the non-root Odoo user")
    if ":latest" in dockerfile:
        errors.append("Dockerfile contains a forbidden latest tag")
    for module in EXPECTED_MODULES:
        if f"odoo_addons/{module}" not in dockerfile:
            errors.append(f"Dockerfile does not copy {module}")

    release_compose = (PACKAGE / "compose.release.yaml").read_text(
        encoding="utf-8"
    )
    for token in [
        "ODOO_CALL_FOLLOWUP_IMAGE:?",
        "/opt/codestra/addons",
        "codestra-odoo-healthcheck",
        "automation-default: disabled",
    ]:
        if token not in release_compose:
            errors.append(f"release Compose file is missing invariant: {token}")
    if ":latest" in release_compose:
        errors.append("release Compose file contains a forbidden latest tag")

    for name in ["compose.install.yaml", "compose.upgrade.yaml"]:
        source = (PACKAGE / name).read_text(encoding="utf-8")
        if "--stop-after-init" not in source:
            errors.append(f"{name} lacks stop-after-init")
        if "--workers=0" not in source or "--max-cron-threads=0" not in source:
            errors.append(f"{name} does not disable workers and cron")
        for module in EXPECTED_MODULES:
            if module not in source:
                errors.append(f"{name} does not include {module}")

    deploy_source = (PACKAGE / "deploy.sh").read_text(encoding="utf-8")
    for token in [
        "REQUIRED_CHECKS",
        "INDEPENDENT_REVIEW",
        "STAGING_ACCEPTANCE",
        "ROLLBACK_REHEARSAL",
        "DATABASE_BACKUP_ID",
        "FILESTORE_BACKUP_ID",
        "PRODUCTION_CONFIRMATION",
        "repository@sha256",
        "ODOO_REMAINS_STOPPED=YES",
    ]:
        if token not in deploy_source:
            errors.append(f"deploy script is missing production gate: {token}")
    if "ALLOW_PRODUCTION_DEPLOY YES" not in deploy_source:
        errors.append("deploy script lacks explicit production authorization")

    for script_name in ["build.sh", "validate.sh", "deploy.sh"]:
        script = PACKAGE / script_name
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            errors.append(
                f"shell syntax error in {script_name}: {result.stderr.strip()}"
            )

    workflow = (
        ROOT
        / ".github"
        / "workflows"
        / "odoo-call-followup-docker-release.yml"
    ).read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s*[^@\s]+@([^\s#]+)", workflow)
    if not action_refs or any(
        not re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs
    ):
        errors.append("GitHub Actions must be pinned to full commit SHAs")
    for validator in [
        "validate_odoo_crm_call_followup.py",
        "validate_odoo_crm_call_followup_api.py",
        "validate_odoo_crm_call_followup_ux.py",
        "validate_odoo_crm_call_followup_automation.py",
    ]:
        if validator not in workflow:
            errors.append(f"Docker CI does not run {validator}")

    sensitive_patterns = [
        re.compile(r"(?i)(api[_-]?key|password|webhook[_-]?secret)\s*=\s*[^<\s$]"),
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ]
    for path in [
        PACKAGE / ".env.example",
        PACKAGE / "compose.automation-secrets.yaml",
        PACKAGE / "build.sh",
        PACKAGE / "deploy.sh",
    ]:
        text = path.read_text(encoding="utf-8")
        for pattern in sensitive_patterns:
            if pattern.search(text):
                errors.append(
                    f"possible literal secret in {path.relative_to(ROOT)}"
                )

    if errors:
        print("ODOO_CALL_FOLLOWUP_DOCKER_RELEASE_VALIDATION=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("ODOO_CALL_FOLLOWUP_DOCKER_RELEASE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
