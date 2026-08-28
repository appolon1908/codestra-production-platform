import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]


def test_platform_authority_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_platform_authority.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Platform authority validation passed" in result.stdout


def test_platform_catalog_has_no_legacy_kyqra_repository() -> None:
    files = [
        ROOT / "contracts/catalog.v1.json",
        ROOT / "composition/runtime-composition.v1.json",
    ]
    for path in files:
        value = json.loads(path.read_text(encoding="utf-8"))
        assert "appolon1908-hue/kyqra\"" not in json.dumps(value, sort_keys=True)


def test_caddy_has_one_documented_git_home() -> None:
    readme = (ROOT / "operations/caddy/README.md").read_text(encoding="utf-8")
    assert "canonical Git home" in readme
    assert "operations/caddy/" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_host_component_has_a_catalog_definition() -> None:
    composition = json.loads(
        (ROOT / "composition/runtime-composition.v1.json").read_text(
            encoding="utf-8"
        )
    )
    defined = {component["id"] for component in composition["components"]}
    referenced = {
        component_id
        for host in composition["hosts"]
        for component_id in host["components"]
    }
    assert referenced <= defined


def _release_manifest() -> dict:
    sha = "0" * 64
    evidence = {
        evidence_class: {
            "path": f"evidence/{evidence_class}.json",
            "sha256": sha,
        }
        for evidence_class in (
            "integration",
            "backup",
            "restore",
            "monitoring",
            "rollback",
        )
    }
    return {
        "schema_version": "platform-release-manifest.v1",
        "release_id": "release-20260828",
        "created_at": "2026-08-28T12:00:00Z",
        "authority": {
            "repository": "appolon1908-hue/codestra-production-platform",
            "git_sha": "a" * 40,
        },
        "contracts": {"path": "contracts/catalog.v1.json", "sha256": sha},
        "runtime": {
            "path": "composition/runtime-composition.v1.json",
            "sha256": sha,
        },
        "services": [
            {
                "service_id": "middleware",
                "repository": "appolon1908-hue/Middleware-",
                "git_sha": "b" * 40,
                "image": {
                    "reference": "ghcr.io/appolon1908-hue/middleware",
                    "digest": f"sha256:{sha}",
                },
                "service_manifest_sha256": sha,
            }
        ],
        "edge": {
            "caddy": {"path": "operations/caddy/Caddyfile", "sha256": sha},
            "kong": {"path": "deploy/kong/control-plane.yml", "sha256": sha},
        },
        "promotion": {
            "identical_digests_required": True,
            "staging": {"status": "accepted", "evidence": evidence},
            "production": {"status": "pending", "evidence": {}},
        },
        "evidence": list(evidence.values()),
    }


def test_accepted_environment_gate_requires_pinned_evidence() -> None:
    schema = json.loads(
        (ROOT / "release/platform-release-manifest.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = _release_manifest()
    manifest["promotion"]["staging"]["evidence"] = {}
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(manifest)


def test_release_manifest_accepts_staging_evidence_before_production() -> None:
    schema = json.loads(
        (ROOT / "release/platform-release-manifest.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(_release_manifest())


def test_production_acceptance_requires_staging_acceptance() -> None:
    schema = json.loads(
        (ROOT / "release/platform-release-manifest.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = _release_manifest()
    manifest["promotion"]["staging"] = {"status": "pending", "evidence": {}}
    production_evidence = deepcopy(manifest["promotion"]["staging"]["evidence"])
    production_evidence.update(
        {
            evidence_class: {
                "path": f"evidence/production-{evidence_class}.json",
                "sha256": "0" * 64,
            }
            for evidence_class in (
                "integration",
                "backup",
                "restore",
                "monitoring",
                "rollback",
                "approval",
            )
        }
    )
    manifest["promotion"]["production"] = {
        "status": "accepted",
        "evidence": production_evidence,
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(manifest)


@pytest.mark.parametrize(
    "missing_class",
    ["integration", "backup", "restore", "monitoring", "rollback", "approval"],
)
def test_production_acceptance_requires_every_evidence_class(
    missing_class: str,
) -> None:
    schema = json.loads(
        (ROOT / "release/platform-release-manifest.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = _release_manifest()
    evidence = deepcopy(manifest["promotion"]["staging"]["evidence"])
    evidence["approval"] = {
        "path": "evidence/production-approval.json",
        "sha256": "0" * 64,
    }
    evidence.pop(missing_class)
    manifest["promotion"]["production"] = {
        "status": "accepted",
        "evidence": evidence,
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(manifest)
