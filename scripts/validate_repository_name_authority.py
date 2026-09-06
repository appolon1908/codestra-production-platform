#!/usr/bin/env python3
"""Validate controlled repository-name mappings without calling GitHub."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "repository-name-aliases.v1.json"
CAPTURE = ROOT / "scripts" / "capture_repository_review_core.py"
EXPECTED = {
    1221155447: (
        "appolon1908-hue/Frontend-Resturant-",
        "appolon1908-hue/restaurant-frontend",
    ),
    1343761049: (
        "appolon1908-hue/transportaion-Frontend",
        "appolon1908-hue/freight-platform-frontend",
    ),
    1343962199: (
        "appolon1908-hue/LARIM-A-Fornt-end",
        "appolon1908-hue/LARIM-A-Frontend",
    ),
    1351353723: (
        "appolon1908-hue/Codesrea-Social-",
        "appolon1908-hue/Codestra-Social-Control-Plane",
    ),
    1350724356: (
        "appolon1908-hue/documentaions",
        "appolon1908-hue/Codestra-Documentation",
    ),
    1350724865: (
        "appolon1908-hue/Infustruction-repo",
        "appolon1908-hue/Codestra-Infrastructure",
    ),
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON {path.relative_to(ROOT)}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} root must be an object")
    return value


def string_assignments(module: ast.Module) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                values[target.id] = value.value
    return values


def resolve_string(node: ast.AST, constants: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    fail("KNOWN_REPOSITORIES entries must be strings or named string constants")
    raise AssertionError("unreachable")


def known_repositories() -> tuple[str, ...]:
    try:
        module = ast.parse(CAPTURE.read_text(encoding="utf-8"), filename=str(CAPTURE))
    except SyntaxError as exc:
        fail(f"capture core has invalid syntax: {exc}")

    constants = string_assignments(module)
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "KNOWN_REPOSITORIES"
            for target in targets
        ):
            continue
        if not isinstance(node.value, ast.Tuple):
            fail("KNOWN_REPOSITORIES must be a literal tuple")
        repositories = tuple(resolve_string(item, constants) for item in node.value.elts)
        if len(repositories) != len(set(repositories)):
            fail("KNOWN_REPOSITORIES contains duplicate repository names")
        return repositories
    fail("capture core does not define KNOWN_REPOSITORIES")
    raise AssertionError("unreachable")


def validate() -> None:
    document = load_json(MANIFEST)
    if document.get("schema_version") != "1.0":
        fail("schema_version must be 1.0")
    if document.get("status") != "PREPARED_NOT_RENAMED":
        fail("rename status changed without a reviewed cutover")
    if document.get("identity_key") != "repository_id":
        fail("repository_id must be the stable identity key")
    if document.get("historical_evidence_immutable") is not True:
        fail("historical evidence must remain immutable")

    mappings = document.get("mappings")
    if not isinstance(mappings, list) or len(mappings) != 6:
        fail("manifest must contain exactly six rename mappings")

    actual: dict[int, tuple[str, str]] = {}
    current_names: set[str] = set()
    target_names: set[str] = set()
    for item in mappings:
        if not isinstance(item, dict):
            fail("rename mapping must be an object")
        repository_id = item.get("repository_id")
        current = item.get("current_repository")
        target = item.get("target_repository_after_cutover")
        if not isinstance(repository_id, int) or repository_id <= 0:
            fail("rename mapping contains an invalid repository ID")
        if repository_id in actual:
            fail(f"duplicate repository ID: {repository_id}")
        if not isinstance(current, str) or not isinstance(target, str):
            fail(f"rename mapping names are invalid for repository ID {repository_id}")
        if current in current_names or target in target_names:
            fail("rename mapping contains duplicate current or target names")
        if item.get("status") != "PREPARED_NOT_RENAMED":
            fail(f"mapping changed state without cutover: {current}")
        actual[repository_id] = (current, target)
        current_names.add(current)
        target_names.add(target)

    if actual != EXPECTED:
        fail("rename mappings do not exactly match the approved stable-ID set")

    inventory = set(known_repositories())
    missing = {current for current, _target in EXPECTED.values()} - inventory
    if missing:
        fail("capture inventory omits current repositories: " + ", ".join(sorted(missing)))
    premature = {target for _current, target in EXPECTED.values()} & inventory
    if premature:
        fail("capture inventory uses target names before cutover: " + ", ".join(sorted(premature)))

    exporter = document.get("postgres_exporter_authority", {})
    if exporter.get("repository_id") != 1350839865:
        fail("PostgreSQL Exporter repository ID is incorrect")
    if exporter.get("repository") != "appolon1908-hue/Codestra-Postgres-Exporter":
        fail("PostgreSQL Exporter principal repository is incorrect")
    if exporter.get("public_hostname") is not None:
        fail("PostgreSQL Exporter may not have a public hostname")
    if exporter.get("private_service_identity") != "postgres-exporter:9187":
        fail("PostgreSQL Exporter private identity is incorrect")
    if exporter.get("forbidden_public_hostname") != "pgex.codestra.media":
        fail("retired PostgreSQL Exporter hostname is not explicitly forbidden")
    if exporter.get("exposure") != "PRIVATE_INTERNAL_ONLY":
        fail("PostgreSQL Exporter must remain private/internal only")


def main() -> None:
    validate()
    print("Production repository-name authority validation: PASS")


if __name__ == "__main__":
    main()
