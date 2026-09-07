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


def test_platform_authority_validator_cannot_be_disabled_by_optimization() -> None:
    result = subprocess.run(
        [sys.executable, "-O", "scripts/validate_platform_authority.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Platform authority validation passed" in result.stdout
    assert "assert " not in (
        ROOT / "scripts/validate_platform_authority.py"
    ).read_text(encoding="utf-8")


def test_unresolved_middleware_candidate_is_not_a_composition_or_contract_source() -> None:
    composition = json.loads(
        (ROOT / "composition/runtime-composition.v1.json").read_text()
    )
    middleware = next(
        item for item in composition["components"] if item["id"] == "middleware"
    )
    assert "composition_input" not in middleware

    catalog = json.loads((ROOT / "contracts/catalog.v1.json").read_text())
    middleware_contracts = [
        item for item in catalog["contracts"] if item["id"].startswith("codestra.middleware.")
    ]
    assert middleware_contracts
    assert {
        item["source"]["repository"] for item in middleware_contracts
    } == {"Codestra-SRL/codestra-middleware"}


def test_container_caddy_uses_shared_network_upstreams() -> None:
    api = (ROOT / "operations/caddy/api.codestra.co.caddy").read_text()
    assert "reverse_proxy 127.0.0.1:" not in api
    assert "reverse_proxy codestra-websocket-gateway-gateway-1:8080" in api
    assert "reverse_proxy codestra-kong-kong-gateway-1:8000" in api


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
            "path": f"evidence/staging/{evidence_class}.json",
            "sha256": sha,
            "environment": "staging",
        }
        for evidence_class in (
            "integration",
            "backup",
            "restore",
            "monitoring",
            "rollback",
        )
    }
    composition = json.loads(
        (ROOT / "composition/runtime-composition.v1.json").read_text()
    )
    repositories = {
        item["id"]: item["source_repository"] for item in composition["components"]
    }
    image_references = {
        service_id: f"ghcr.io/appolon1908-hue/{service_id}"
        for service_id in composition["release_service_ids"]
    }
    image_references.update({
        "middleware": "ghcr.io/codestra-srl/codestra-middleware",
        "nats-jetstream": "ghcr.io/codestra-srl/codestra-middleware",
        "temporal": "ghcr.io/codestra-srl/codestra-middleware",
        "middleware-external-webhook-worker": "ghcr.io/codestra-srl/codestra-middleware",
        "middleware-breero-odoo-worker": "ghcr.io/codestra-srl/codestra-middleware",
        "odoo-19": "ghcr.io/codestra-srl/codestra-odoo",
        "email-reseller-api": "ghcr.io/appolon1908-hue/email-reseller",
        "stalwart": "stalwartlabs/stalwart",
        "redis": "redis",
        "prometheus": "prom/prometheus",
        "alertmanager": "prom/alertmanager",
        "node-exporter": "prom/node-exporter",
        "postgres-exporter": "docker.io/prometheuscommunity/postgres-exporter",
        "redis-exporter": "docker.io/oliver006/redis_exporter",
        "cadvisor": "gcr.io/cadvisor/cadvisor",
        "blackbox-exporter": "prom/blackbox-exporter",
    })
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
                "service_id": service_id,
                "repository": repositories[service_id],
                "git_sha": "b" * 40,
                "image": {
                    "reference": image_references[service_id],
                    "digest": f"sha256:{sha}",
                },
                "service_manifest_sha256": sha,
            }
            for service_id in composition["release_service_ids"]
        ],
        "edge": {
            "caddy": {"path": "release/caddy-edge-bundle.v1.json", "sha256": sha},
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


def test_release_manifest_rejects_any_missing_deployed_service() -> None:
    schema = json.loads(
        (ROOT / "release/platform-release-manifest.v1.schema.json").read_text()
    )
    manifest = _release_manifest()
    for service in list(manifest["services"]):
        incomplete = deepcopy(manifest)
        incomplete["services"] = [
            item for item in incomplete["services"] if item != service
        ]
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(incomplete)


def test_release_manifest_binds_each_service_to_its_authoritative_repository() -> None:
    schema = json.loads((ROOT / "release/platform-release-manifest.v1.schema.json").read_text())
    manifest = _release_manifest()
    for index in range(len(manifest["services"])):
        wrong = deepcopy(manifest)
        wrong["services"][index]["repository"] = "appolon1908-hue/unrelated"
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(wrong)


def test_release_manifest_binds_each_service_to_its_approved_image_name() -> None:
    schema = json.loads((ROOT / "release/platform-release-manifest.v1.schema.json").read_text())
    manifest = _release_manifest()
    for index in range(len(manifest["services"])):
        wrong = deepcopy(manifest)
        wrong["services"][index]["image"]["reference"] = "ghcr.io/appolon1908-hue/unrelated"
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(wrong)


def test_websocket_gateway_and_telephony_contracts_are_release_bearing() -> None:
    composition = json.loads((ROOT / "composition/runtime-composition.v1.json").read_text())
    assert "websocket-gateway" in composition["release_service_ids"]
    assert "integration-control-plane" in composition["release_service_ids"]
    catalog = json.loads((ROOT / "contracts/catalog.v1.json").read_text())
    ids = {item["id"] for item in catalog["contracts"]}
    assert {
        "codestra.telephony.calling-api.v1",
        "codestra.telephony.calling-events.v1",
        "codestra.telephony.calling-ecosystem.v1",
    } <= ids


@pytest.mark.parametrize("field,path", [
    ("contracts", "README.md"), ("runtime", "README.md"),
])
def test_release_manifest_requires_canonical_authority_paths(field, path) -> None:
    schema = json.loads((ROOT / "release/platform-release-manifest.v1.schema.json").read_text())
    manifest = _release_manifest()
    manifest[field]["path"] = path
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(manifest)


@pytest.mark.parametrize("edge", ["caddy", "kong"])
def test_release_manifest_requires_complete_canonical_edge_paths(edge) -> None:
    schema = json.loads((ROOT / "release/platform-release-manifest.v1.schema.json").read_text())
    manifest = _release_manifest()
    manifest["edge"][edge]["path"] = "README.md"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(manifest)


def test_caddy_bundle_hashes_every_deployable_configuration() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_platform_authority.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Platform authority validation passed" in result.stdout


def test_container_caddy_root_excludes_host_only_klyrow_listener() -> None:
    root = (ROOT / "operations/caddy/Caddyfile").read_text()
    assert "import klyrow-events.caddy" not in root
    fragment = (ROOT / "operations/caddy/klyrow-events.caddy").read_text()
    assert "Host-Caddy-only" in fragment


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
                "path": f"evidence/production/{evidence_class}.json",
                "sha256": "0" * 64,
                "environment": "production",
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
        "path": "evidence/production/approval.json",
        "sha256": "0" * 64,
        "environment": "production",
    }
    evidence.pop(missing_class)
    manifest["promotion"]["production"] = {
        "status": "accepted",
        "evidence": evidence,
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(manifest)
