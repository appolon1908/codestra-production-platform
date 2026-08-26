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
EXPECTED_INTEGRATION_SHA = "b9b55274d726b2375f0a48ae30a2b1369c47e91c"
EXPECTED_COMPONENTS = {
    "core": "3bf43b689da96eb1ab2444c30133a2dc43563be4",
    "api": "985869b17ebd3211b87c48cf620bb34a011b910b",
    "ux": "3bcca91f62a8e1ca67c9e4b850a72a9f317ed431",
    "automation": "fde96222979e43f213f49eeee3d695bfdc862ddb",
}
EXPECTED_MODULES = {
    "codestra_crm_call_followup",
    "codestra_crm_call_followup_api",
    "codestra_crm_call_followup_ux",
    "codestra_crm_call_followup_automation",
}


def check_shell(path: Path, errors: list[str]) -> None:
    result = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        errors.append(
            f"shell syntax error in {path.relative_to(ROOT)}: "
            f"{result.stderr.strip()}"
        )


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
        PACKAGE / ".env.example",
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
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid release manifest: {exc}")
        manifest = {}

    if manifest.get("integration_source_sha") != EXPECTED_INTEGRATION_SHA:
        errors.append("release manifest integration SHA is not locked")
    if manifest.get("component_source_shas") != EXPECTED_COMPONENTS:
        errors.append("release manifest component SHAs are not locked")
    if set(manifest.get("modules", [])) != EXPECTED_MODULES:
        errors.append("release manifest module set is incomplete")
    defaults = manifest.get("runtime_defaults", {})
    for key in (
        "automation_remote_delivery_enabled",
        "production_dialing_enabled",
        "direct_vicidial_writes",
        "direct_carrier_writes",
    ):
        if defaults.get(key) is not False:
            errors.append(f"runtime default must remain false: {key}")

    dockerfile = (PACKAGE / "Dockerfile").read_text(encoding="utf-8")
    for token in (
        "FROM ${ODOO_BASE_IMAGE}",
        "ARG ODOO_BASE_IMAGE=odoo@sha256:",
        f'com.codestra.release.integration-sha="{EXPECTED_INTEGRATION_SHA}"',
        "\nUSER odoo\n",
        "codestra-odoo-healthcheck",
    ):
        if token not in dockerfile:
            errors.append(f"Dockerfile is missing invariant: {token}")
    if ":latest" in dockerfile:
        errors.append("Dockerfile contains a forbidden latest tag")
    for module in EXPECTED_MODULES:
        if f"odoo_addons/{module}" not in dockerfile:
            errors.append(f"Dockerfile does not copy {module}")

    release_compose = (PACKAGE / "compose.release.yaml").read_text(
        encoding="utf-8"
    )
    for token in (
        "ODOO_CALL_FOLLOWUP_IMAGE:?",
        "ODOO_CALL_FOLLOWUP_RELEASE_SHA:?",
        "/opt/codestra/addons",
        "codestra-odoo-healthcheck",
        "automation-default: disabled",
    ):
        if token not in release_compose:
            errors.append(f"release Compose file is missing invariant: {token}")
    if ":latest" in release_compose:
        errors.append("release Compose file contains a forbidden latest tag")

    for name, operation in (
        ("compose.install.yaml", "--init="),
        ("compose.upgrade.yaml", "--update="),
    ):
        source = (PACKAGE / name).read_text(encoding="utf-8")
        for token in (operation, "--stop-after-init", "--workers=0", "--max-cron-threads=0"):
            if token not in source:
                errors.append(f"{name} is missing invariant: {token}")
        for module in EXPECTED_MODULES:
            if module not in source:
                errors.append(f"{name} does not include {module}")

    deploy_source = (PACKAGE / "deploy.sh").read_text(encoding="utf-8")
    for token in (
        "REQUIRED_CHECKS",
        "INDEPENDENT_REVIEW",
        "STAGING_ACCEPTANCE",
        "ROLLBACK_REHEARSAL",
        "DATABASE_BACKUP_ID",
        "FILESTORE_BACKUP_ID",
        "PRODUCTION_CONFIRMATION",
        "ALLOW_PRODUCTION_DEPLOY YES",
        "repository@sha256",
        "ODOO_REMAINS_STOPPED=YES",
    ):
        if token not in deploy_source:
            errors.append(f"deploy script is missing production gate: {token}")

    for script_name in ("build.sh", "validate.sh", "deploy.sh"):
        check_shell(PACKAGE / script_name, errors)

    workflow = (
        ROOT / ".github" / "workflows" / "odoo-call-followup-docker-release.yml"
    ).read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s*[^@\s]+@([^\s#]+)", workflow)
    if not action_refs or any(
        not re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs
    ):
        errors.append("GitHub Actions must be pinned to full commit SHAs")
    for validator in (
        "validate_odoo_crm_call_followup.py",
        "validate_odoo_crm_call_followup_api.py",
        "validate_odoo_crm_call_followup_ux.py",
        "validate_odoo_crm_call_followup_automation.py",
        "validate_odoo_call_followup_docker_release.py",
    ):
        if validator not in workflow:
            errors.append(f"Docker CI does not run {validator}")

    # Repository-wide gitleaks is the authoritative credential scanner. This
    # structural validator deliberately does not embed secret detector fixtures,
    # because those fixtures correctly resemble secrets to the real scanner.

    if errors:
        print("ODOO_CALL_FOLLOWUP_DOCKER_RELEASE_VALIDATION=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("ODOO_CALL_FOLLOWUP_DOCKER_RELEASE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
