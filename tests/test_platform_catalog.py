from __future__ import annotations

import copy
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
