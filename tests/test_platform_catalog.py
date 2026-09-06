from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

from tools.check_platform_catalog import deployment_blockers, load_catalog, validate_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/platform-catalog.yaml"


def catalog():
    return load_catalog(CATALOG)


def test_repository_platform_catalog_is_structurally_valid() -> None:
    assert validate_catalog(ROOT, catalog()) == []


def test_external_delivery_and_telephony_default_disabled() -> None:
    unsafe = [
        row["feature_id"]
        for row in catalog()["features"]
        if row["side_effects"] in {"external_writes", "telephony"}
        and row["runtime_default"] != "disabled"
    ]
    assert unsafe == []


def test_campaign_automation_is_not_a_default_deployment_candidate() -> None:
    row = next(
        item
        for item in catalog()["features"]
        if item["feature_id"] == "middleware-campaign-automation"
    )
    assert row["deployment_candidate"] is False


def test_deployment_gate_reports_known_middleware_blockers() -> None:
    blockers = deployment_blockers(
        catalog(),
        {"middleware-callback-api", "middleware-campaign-automation"},
    )
    rules = {item.location for item in blockers}
    assert "kong-route-authority-duplication" in rules
    assert "campaign-lifecycle-entrypoints" in rules
    assert "generated-container-service-identities" in rules
    assert "shared-postgresql-runtime-pitr" in rules


def test_accepted_risk_cannot_bypass_required_server_push_gap() -> None:
    value = catalog()
    gap = next(
        item
        for item in value["known_gaps"]
        if item["required_before_server_push"]
        and item["affected_features"]
    )
    gap["status"] = "accepted_risk"
    blockers = deployment_blockers(value, {gap["affected_features"][0]})
    assert gap["gap_id"] in {item.location for item in blockers}


def test_resolved_gap_requires_structured_existing_evidence() -> None:
    value = catalog()
    gap = next(
        item
        for item in value["known_gaps"]
        if item["required_before_server_push"]
        and item["affected_features"]
    )
    feature_id = gap["affected_features"][0]
    gap["status"] = "resolved"

    for invalid_resolution in (True, "done", {"summary": "done", "evidence": []}):
        gap["resolution"] = invalid_resolution
        rules = {item.rule for item in validate_catalog(ROOT, value)}
        assert "gap-resolution" in rules
        blockers = deployment_blockers(value, {feature_id})
        assert gap["gap_id"] in {item.location for item in blockers}

    gap["resolution"] = {
        "summary": "Synthetic resolution evidence for validation coverage.",
        "evidence": ["docs/architecture/API_GOVERNANCE.md"],
    }
    assert "gap-resolution-evidence" in {
        item.rule
        for item in validate_catalog(ROOT, value)
        if item.location == gap["gap_id"]
    }
    blockers = deployment_blockers(value, {feature_id})
    assert gap["gap_id"] in {item.location for item in blockers}


def test_resolved_gap_rejects_non_repository_evidence() -> None:
    value = catalog()
    gap = next(item for item in value["known_gaps"] if item["required_before_server_push"])
    gap["status"] = "resolved"
    for reference in (
        "docs/missing-resolution-evidence.md",
        "external:unverified",
        "/etc/passwd",
        "../outside-repository",
        "docs/../AGENTS.md",
    ):
        gap["resolution"] = {"summary": "Claimed resolution.", "evidence": [reference]}
        rules = {item.rule for item in validate_catalog(ROOT, value)}
        assert "gap-resolution-evidence" in rules


def test_resolved_gap_evidence_must_be_git_tracked() -> None:
    value = catalog()
    gap = next(item for item in value["known_gaps"] if item["required_before_server_push"])
    gap["status"] = "resolved"
    untracked = ROOT / ".catalog-untracked-evidence-test"
    untracked.write_text("runtime-only evidence\n", encoding="utf-8")
    try:
        gap["resolution"] = {
            "summary": "Claimed resolution from untracked runtime metadata.",
            "evidence": [str(untracked.relative_to(ROOT))],
        }
        rules = {item.rule for item in validate_catalog(ROOT, value)}
        assert "gap-resolution-evidence" in rules
    finally:
        untracked.unlink()


def test_deployment_candidate_must_be_boolean() -> None:
    value = catalog()
    value["features"][0]["deployment_candidate"] = "true"
    rules = {item.rule for item in validate_catalog(ROOT, value)}
    assert "feature-deployment-candidate" in rules


def test_required_server_push_flag_must_be_boolean() -> None:
    value = catalog()
    value["known_gaps"][0]["required_before_server_push"] = 0
    rules = {item.rule for item in validate_catalog(ROOT, value)}
    assert "gap-server-push-flag" in rules


def test_required_gap_must_name_at_least_one_affected_feature() -> None:
    value = catalog()
    gap = next(item for item in value["known_gaps"] if item["required_before_server_push"])
    gap["affected_features"] = []
    rules = {item.rule for item in validate_catalog(ROOT, value)}
    assert "gap-feature" in rules


def test_resolved_gap_rejects_unbound_general_document() -> None:
    value = catalog()
    gap = next(item for item in value["known_gaps"] if item["required_before_server_push"])
    gap["status"] = "resolved"
    gap["resolution"] = {
        "summary": "Claimed resolution.",
        "evidence": ["docs/architecture/API_GOVERNANCE.md"],
    }
    rules = {item.rule for item in validate_catalog(ROOT, value)}
    assert "gap-resolution-evidence" in rules


def test_resolved_gap_validates_every_claimed_proof_artifact(tmp_path) -> None:
    repository = tmp_path / "repository"
    wrapper_dir = repository / "evidence/catalog-gaps/runtime-gap"
    wrapper_dir.mkdir(parents=True)
    proof = repository / "evidence/runtime-proof.json"
    proof.write_text('{"result":"pass"}\n', encoding="utf-8")
    wrapper = wrapper_dir / "resolution.json"
    wrapper.write_text(json.dumps({
        "schema": "codestra.catalog-gap-resolution.v1",
        "gap_id": "runtime-gap",
        "status": "resolved",
        "source_sha": "a" * 40,
        "observed_at": "2026-09-06T00:00:00Z",
        "artifacts": [{
            "path": "evidence/runtime-proof.json",
            "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
        }],
    }), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "add", "evidence"], cwd=repository, check=True)
    value = {
        "version": 1,
        "systems": [],
        "features": [],
        "apis": [],
        "known_gaps": [{
            "gap_id": "runtime-gap", "severity": "critical", "status": "resolved",
            "owner": "platform", "required_before_server_push": False,
            "affected_features": [], "remediation": "capture proof",
            "resolution": {"summary": "verified", "evidence": [
                "evidence/catalog-gaps/runtime-gap/resolution.json"
            ]},
        }],
    }
    assert validate_catalog(repository, value) == []
    proof.write_text('{"result":"changed"}\n', encoding="utf-8")
    assert "gap-resolution-evidence" in {
        finding.rule for finding in validate_catalog(repository, value)
    }


def test_duplicate_public_route_is_rejected() -> None:
    value = catalog()
    value["apis"].append(copy.deepcopy(value["apis"][0]))
    value["apis"][-1]["api_id"] = "duplicate-healthz"
    rules = {item.rule for item in validate_catalog(ROOT, value)}
    assert "duplicate-api-route" in rules


def test_public_business_api_cannot_bypass_kong() -> None:
    value = catalog()
    row = next(item for item in value["apis"] if item["api_id"] == "callback-control")
    row["ingress"] = "caddy_browser"
    rules = {item.rule for item in validate_catalog(ROOT, value)}
    assert "public-api-bypass" in rules


def test_mutation_requires_idempotency_or_documented_exemption() -> None:
    value = catalog()
    row = next(item for item in value["apis"] if item["api_id"] == "campaign-results")
    row["idempotency"] = "not_required"
    rules = {item.rule for item in validate_catalog(ROOT, value)}
    assert "mutation-idempotency" in rules


def test_nonactive_feature_cannot_default_enabled() -> None:
    value = catalog()
    row = next(item for item in value["features"] if item["feature_id"] == "provisioning-production")
    row["runtime_default"] = "enabled"
    rules = {item.rule for item in validate_catalog(ROOT, value)}
    assert "unsafe-feature-default" in rules
    assert "unsafe-side-effect-default" in rules
