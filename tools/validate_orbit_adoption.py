#!/usr/bin/env python3
"""Validate the fail-closed Codestra Orbit production adoption contract."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "orbit" / "adoption-manifest.json"
SCHEMA_PATH = ROOT / "orbit" / "contracts" / "adoption-manifest.schema.json"
LEDGER_PATH = ROOT / "orbit" / "adoption-ledger.json"
GATES_PATH = ROOT / "orbit" / "runtime-activation-gates.json"

CONTRACT_ID = "codestra-orbit-v2.0.0"
AUTHORITY_REPOSITORY = "appolon1908-hue/codestra-production-platform"
SOURCE_REPOSITORY = "appolon1908-hue/SDK-repository"
TARGET_BRANCH = "release/production-activation"
EXPECTED_PACKAGES = {
    "@corporate/auth-ui",
    "@corporate/brand-registry",
    "@corporate/content-sdk",
    "@corporate/design-tokens",
    "@corporate/eslint-config",
    "@corporate/icons",
    "@corporate/stylelint-config",
    "@corporate/testing",
    "@corporate/ui",
}
EXPECTED_CHECKS = {
    "Codestra Orbit authority",
    "Contract validation",
    "Generated SDKs",
    "Compatibility gates",
    "Workspace CI",
}
EXPECTED_GATE_IDS = (
    "sdk_protected_release",
    "package_artifact_digests",
    "consumer_adoption_ledger",
    "domain_registry",
    "identity_clients",
    "immutable_application_artifacts",
    "edge_source_locks",
    "staging_visual_evidence",
    "accessibility_certification",
    "auth_session_certification",
    "observability_certification",
    "rollback_rehearsal",
    "production_environment_gate",
    "production_readback",
)
PENDING_STATUS = "PREPARED_PENDING_SDK_PROTECTED_RELEASE"
CERTIFIED_STATUS = "PRODUCTION_CERTIFIED"
FORBIDDEN_PREFIXES = (
    "orbit/packages/",
    "orbit/dist/",
    "orbit/ui/",
    "orbit/components/",
)
FORBIDDEN_SUFFIXES = (".tgz", ".tar", ".tar.gz", ".zip")


class ContractError(ValueError):
    """Raised when the Orbit adoption contract is unsafe or inconsistent."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def validate_schema(manifest: dict[str, Any], schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}"
            for error in errors
        )
        raise ContractError(f"manifest schema validation failed: {details}")


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [line for line in result.stdout.splitlines() if line]
    return [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
    ]


def validate_repository_paths(paths: Iterable[str]) -> None:
    violations: list[str] = []
    for raw_path in paths:
        path = raw_path.replace("\\", "/")
        lower = path.lower()
        if any(path.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            violations.append(path)
        if path.startswith("orbit/") and any(
            lower.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES
        ):
            violations.append(path)
    if violations:
        raise ContractError(
            "contract-only repository contains competing UI/package artifacts: "
            + ", ".join(sorted(set(violations)))
        )


def validate_packages(manifest: dict[str, Any]) -> None:
    packages = manifest["packages"]
    names = {package["name"] for package in packages}
    if names != EXPECTED_PACKAGES or len(packages) != len(names):
        raise ContractError("package inventory must contain the exact nine Orbit packages")

    pending = manifest["status"] == PENDING_STATUS
    for package in packages:
        if pending and (
            package["sha256"] is not None or package["installAllowed"] is not False
        ):
            raise ContractError(
                "pending SDK candidate packages must have no digest and remain non-installable"
            )
        if package["installAllowed"] and not re.fullmatch(
            r"[0-9a-f]{64}", package["sha256"] or ""
        ):
            raise ContractError(
                f"installable package lacks a valid digest: {package['name']}"
            )


def validate_manifest_state(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    gates: dict[str, Any],
) -> None:
    if manifest["repository"] != AUTHORITY_REPOSITORY:
        raise ContractError("wrong adoption authority repository")
    if manifest["targetBranch"] != TARGET_BRANCH:
        raise ContractError("Orbit adoption must target the protected release branch")
    if manifest["adoptionMode"] != "contract-only":
        raise ContractError("production platform must remain contract-only")
    if manifest["domain"] is not None or manifest["domainStatus"] != "not-applicable":
        raise ContractError("runtime infrastructure must not invent a public domain")

    source = manifest["sourceAuthority"]
    if source["repository"] != SOURCE_REPOSITORY or source["pullRequest"] != 75:
        raise ContractError("wrong Orbit package source authority")
    if {check["name"] for check in source["candidateChecks"]} != EXPECTED_CHECKS:
        raise ContractError("candidate check inventory is incomplete or duplicated")
    if any(check["status"] != "PASS" for check in source["candidateChecks"]):
        raise ContractError("recorded exact-head candidate checks must be PASS")

    if ledger["contractId"] != CONTRACT_ID:
        raise ContractError("consumer ledger contract ID mismatch")
    if ledger["authorityRepository"] != AUTHORITY_REPOSITORY:
        raise ContractError("consumer ledger authority mismatch")
    if not isinstance(ledger.get("entries"), list):
        raise ContractError("consumer ledger entries must be an array")

    gate_items = gates.get("gates")
    if not isinstance(gate_items, list):
        raise ContractError("runtime gates must be an array")
    gate_ids = tuple(item.get("id") for item in gate_items)
    if gate_ids != EXPECTED_GATE_IDS:
        raise ContractError("runtime gate inventory or order is incorrect")
    if gates.get("runtimeMutationsInThisChange") is not False:
        raise ContractError("this source-only adoption change cannot mutate runtime")

    pending = manifest["status"] == PENDING_STATUS
    if pending:
        if source["protectedReleaseSha"] is not None or source["releaseTag"] is not None:
            raise ContractError("pending contract cannot claim a protected SDK release")
        if manifest["productionReady"] or manifest["runtimeActivated"]:
            raise ContractError("pending contract cannot claim production readiness")
        if gates.get("overallStatus") != "BLOCKED":
            raise ContractError("pending contract runtime gate must remain BLOCKED")
        if any(item.get("status") != "PENDING" for item in gate_items):
            raise ContractError("all current activation gates must remain PENDING")
        if ledger.get("status") != "PENDING_CONSUMER_ADOPTION":
            raise ContractError("consumer ledger must remain pending")
        if ledger["entries"]:
            raise ContractError("pending initial contract cannot claim consumer adoption")
        if not manifest.get("blockers"):
            raise ContractError("pending contract must record its blockers")

    certified = manifest["status"] == CERTIFIED_STATUS
    if certified:
        if not re.fullmatch(r"[0-9a-f]{40}", source["protectedReleaseSha"] or ""):
            raise ContractError("certified contract requires protected SDK source SHA")
        if not source["releaseTag"]:
            raise ContractError("certified contract requires a protected release tag")
        if not all(
            package["installAllowed"]
            and re.fullmatch(r"[0-9a-f]{64}", package["sha256"] or "")
            for package in manifest["packages"]
        ):
            raise ContractError("certified contract requires all package digests")
        if not ledger["entries"]:
            raise ContractError("certified contract requires consumer adoption records")
        if ledger.get("status") != "CERTIFIED":
            raise ContractError("certified contract requires a certified ledger")
        if gates.get("overallStatus") != "PASS":
            raise ContractError("certified contract requires overall runtime PASS")
        if any(item.get("status") not in {"PASS", "N/A"} for item in gate_items):
            raise ContractError("certified contract has an incomplete runtime gate")
        if not manifest["productionReady"] or not manifest["runtimeActivated"]:
            raise ContractError("certified contract must declare ready and activated")
        if manifest["blockers"]:
            raise ContractError("certified contract cannot retain blockers")

    if manifest["productionReady"] and not certified:
        raise ContractError("only a certified contract may claim production readiness")
    if manifest["runtimeActivated"] and not certified:
        raise ContractError("only a certified contract may claim runtime activation")


def validate_contract(
    manifest: dict[str, Any],
    schema: dict[str, Any],
    ledger: dict[str, Any],
    gates: dict[str, Any],
    paths: Iterable[str],
) -> None:
    validate_schema(manifest, schema)
    validate_repository_paths(paths)
    validate_packages(manifest)
    validate_manifest_state(manifest, ledger, gates)


def main() -> None:
    manifest = load_json(MANIFEST_PATH)
    schema = load_json(SCHEMA_PATH)
    ledger = load_json(LEDGER_PATH)
    gates = load_json(GATES_PATH)
    validate_contract(manifest, schema, ledger, gates, tracked_paths())
    print("CODESTRA_ORBIT_ADOPTION_CONTRACT=PASS")
    print(f"STATUS={manifest['status']}")
    print(f"PACKAGES={len(manifest['packages'])}/9")
    print(f"RUNTIME_GATES={len(gates['gates'])}/{len(EXPECTED_GATE_IDS)}")
    print("PRODUCTION_READY=FALSE")
    print("RUNTIME_ACTIVATED=FALSE")


if __name__ == "__main__":
    main()
