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
CAPTURE = ROOT / "scripts" / "capture_repository_review.py"
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


def known_repositories() -> tuple[str, ...]:
    try:
        module = ast.parse(CAPTURE.read_text(encoding="utf-8"), filename=str(CAPTURE))
    except SyntaxError as exc:
        fail(f"capture script has invalid syntax: {exc}")
    for node in module.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "KNOWN_REPOSITORIES" in targets:
                value = ast.literal_eval(node.value)
                if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
                    return value
                fail("KNOWN_REPOSITORIES must be a literal tuple of strings")
    fail("capture script does not define KNOWN_REPOSITORIES")


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
    actual = {
        item["repository_id"]: (
            item["current_repository"],
            item["target_repository_after_cutover"],
        )
        for item in mappings
        if isinstance(item, dict)
    }
    if actual != EXPECTED:
        fail("rename mappings do not exactly match the approved stable-ID set")
    if any(item.get("status") != "PREPARED_NOT_RENAMED" for item in mappings):
        fail("an individual mapping changed state without cutover")

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
