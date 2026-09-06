#!/usr/bin/env python3
"""Validate central contract, composition, release, Caddy, and Kyqra authority."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_REPOSITORY = "appolon1908-hue/codestra-production-platform"
AUTHORITY_BRANCH = "release/production-activation"
CANONICAL_KYQRA_REPOSITORY = "appolon1908-hue/kyqra-crawler"
RETIRED_KYQRA_REPOSITORY = "appolon1908-hue/kyqra"


def load(path: str) -> dict:
    value = json.loads((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain an object"
    return value


def validate_authority(value: dict, label: str) -> None:
    assert value.get("authority") == {
        "repository": AUTHORITY_REPOSITORY,
        "branch": AUTHORITY_BRANCH,
    }, f"{label} authority is not canonical"


def validate_catalog() -> None:
    catalog = load("contracts/catalog.v1.json")
    assert catalog.get("schema_version") == "contract-catalog.v1"
    validate_authority(catalog, "contract catalog")
    contracts = catalog.get("contracts")
    assert isinstance(contracts, list) and contracts
    ids = [item.get("id") for item in contracts]
    assert all(isinstance(item, str) and item for item in ids)
    assert len(ids) == len(set(ids)), "contract IDs must be unique"
    for contract in contracts:
        source = contract.get("source", {})
        repository = source.get("repository")
        path = source.get("path")
        assert isinstance(repository, str) and repository
        assert isinstance(path, str) and path
        assert repository != RETIRED_KYQRA_REPOSITORY
        if repository == AUTHORITY_REPOSITORY:
            assert (ROOT / path).is_file(), f"missing catalog source: {path}"


def validate_composition() -> None:
    composition = load("composition/runtime-composition.v1.json")
    assert composition.get("schema_version") == "runtime-composition.v1"
    validate_authority(composition, "runtime composition")
    components = composition.get("components")
    assert isinstance(components, list) and components
    ids = [item.get("id") for item in components]
    assert len(ids) == len(set(ids)), "component IDs must be unique"
    by_id = {item["id"]: item for item in components}
    assert by_id["caddy"]["source_path"] == "operations/caddy"
    assert by_id["kyqra-crawler"]["source_repository"] == CANONICAL_KYQRA_REPOSITORY
    host_components = {
        component_id
        for host in composition.get("hosts", [])
        for component_id in host.get("components", [])
    }
    unresolved = host_components - set(by_id)
    assert not unresolved, f"undefined host components: {sorted(unresolved)}"
    repositories = {item.get("source_repository") for item in components}
    assert RETIRED_KYQRA_REPOSITORY not in repositories
    for component in components:
        if component.get("source_repository") == AUTHORITY_REPOSITORY:
            assert (ROOT / component["source_path"]).exists()
        composition_input = component.get("composition_input")
        if composition_input:
            assert (ROOT / composition_input).is_file(), (
                f"missing composition input: {composition_input}"
            )


def validate_release_schema() -> None:
    schema = load("release/platform-release-manifest.v1.schema.json")
    assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
    authority = schema["properties"]["authority"]["properties"]
    assert authority["repository"]["const"] == AUTHORITY_REPOSITORY
    assert authority["git_sha"]["$ref"] == "#/$defs/git_sha"
    assert schema["$defs"]["git_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert schema["$defs"]["image_digest"]["pattern"] == (
        "^sha256:[0-9a-f]{64}$"
    )
    gate = schema["$defs"]["environment_gate"]
    evidence = gate["properties"]["evidence"]
    required_evidence = {"integration", "backup", "restore", "monitoring", "rollback"}
    assert set(evidence["properties"]) == required_evidence | {"approval"}
    assert set(
        gate["allOf"][0]["then"]["properties"]["evidence"]["required"]
    ) == required_evidence
    production_gate = schema["$defs"]["production_gate"]
    assert production_gate["allOf"][0]["$ref"] == "#/$defs/environment_gate"
    assert production_gate["allOf"][1]["then"]["properties"]["evidence"][
        "required"
    ] == ["approval"]
    promotion = schema["properties"]["promotion"]
    assert promotion["allOf"][0]["then"]["properties"]["staging"][
        "properties"
    ]["status"]["const"] == "accepted"


def validate_caddy_home() -> None:
    caddy_root = (ROOT / "operations/caddy/Caddyfile").read_text(encoding="utf-8")
    assert "import snippets/*.caddy" in caddy_root
    assert "import api.codestra.co.caddy" in caddy_root
    assert "import auth.codestra.co.caddy" in caddy_root
    api = (ROOT / "operations/caddy/api.codestra.co.caddy").read_text(
        encoding="utf-8"
    )
    auth = (ROOT / "operations/caddy/auth.codestra.co.caddy").read_text(
        encoding="utf-8"
    )
    snippets = (ROOT / "operations/caddy/snippets/security-headers.caddy").read_text(
        encoding="utf-8"
    )
    assert "api.codestra.co" in api and "import security_headers" in api
    assert "reverse_proxy 127.0.0.1:18102" in api
    assert "reverse_proxy 127.0.0.1:18101" in api
    assert "reverse_proxy codestra-websocket-gateway-gateway-1:8080" not in api
    assert "reverse_proxy codestra-kong-kong-gateway-1:8000" not in api
    assert "auth.codestra.co" in auth and "import security_headers" in auth
    assert "reverse_proxy keycloak:8080" in auth
    assert re.search(r"\(security_headers\)\s*\{", snippets)


def main() -> int:
    validate_catalog()
    validate_composition()
    validate_release_schema()
    validate_caddy_home()
    print(
        "Platform authority validation passed: contract catalog, runtime "
        "composition, release manifest, Caddy home, and Kyqra source are canonical."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
