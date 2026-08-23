from pathlib import Path

import yaml

from tools.check_integration_architecture import load_yaml, validate, validate_runtime


ROOT = Path(__file__).parents[1]
POLICY = load_yaml(ROOT / "config/integration-policy.yaml")
REGISTRIES = load_yaml(ROOT / "config/integration-registries.yaml")


def test_constitution_is_default_deny_and_has_no_exceptions():
    assert POLICY["default_decision"] == "deny"
    assert POLICY["exceptions"] == []


def test_all_application_databases_have_one_declared_owner():
    owners = [value["database_owner"] for value in POLICY["systems"].values()]
    owned = [value for value in owners if value != "none"]
    assert len(owned) == len(set(owned))


def test_prohibited_business_shortcuts_are_explicit():
    assert {"klyrow", "postal", "telnexa", "jasmin", "vicidial-db"} <= set(POLICY["systems"]["odoo"]["forbidden_targets"])
    assert {"odoo-db", "middleware-db", "klyrow-db", "telnexa-db", "vicidial-db"} <= set(POLICY["systems"]["n8n"]["forbidden_targets"])


def test_registry_references_have_bounded_retry_and_circuits():
    for connector in REGISTRIES["connectors"]:
        assert connector["retry_policy"] in REGISTRIES["retry_policies"]
        assert connector["circuit_breaker_policy"] in REGISTRIES["circuit_breaker_policies"]
        assert connector["timeout_seconds"] > 0


def test_repository_architecture_scan_passes():
    assert validate(ROOT, POLICY, REGISTRIES, None) == []


def test_runtime_fixture_passes():
    assert validate_runtime(ROOT / "tests/fixtures/runtime-architecture-pass.json", POLICY) == []


def test_runtime_fixture_fails_closed_on_each_critical_boundary():
    findings = validate_runtime(ROOT / "tests/fixtures/runtime-architecture-fail.json", POLICY)
    assert {finding.rule for finding in findings} == {
        "private-port-published", "unknown-runtime-destination",
        "unknown-service-account", "unregistered-public-endpoint",
    }


def test_machine_policy_and_registries_are_secret_free():
    serialized = yaml.safe_dump({"policy": POLICY, "registries": REGISTRIES}).lower()
    assert "password:" not in serialized
    assert "client_secret:" not in serialized
