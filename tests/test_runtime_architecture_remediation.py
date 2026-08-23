from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def contract():
    return yaml.safe_load((ROOT / "config/runtime-architecture-remediation.yaml").read_text())


def test_provider_address_ownership_is_exact():
    owners = contract()["provider_owners"]
    assert owners["klyrow"]["private_address"] == "10.40.0.4"
    assert owners["telnexa"]["private_address"] == "10.40.0.4"
    assert owners["vicidial"]["private_address"] == "10.40.0.2"
    for item in contract()["endpoint_overrides"]:
        if item["owner"] in {"klyrow", "telnexa"}:
            assert "10.40.0.2" not in item["value"]
            assert "10.40.0.4" in item["value"]


def test_canonical_websocket_authority():
    data = contract()
    assert data["canonical_api_host"] == "api.codestra.co"
    assert data["canonical_websocket_url"] == "wss://api.codestra.co/ws/agent"
    websocket = [x for x in data["endpoint_overrides"] if x["variable"] == "PUBLIC_WS_URL"]
    assert websocket == [{
        "project": "codestra-websocket-gateway", "service": "gateway",
        "variable": "PUBLIC_WS_URL", "value": "wss://api.codestra.co/ws/agent",
        "owner": "middleware",
    }]


def test_network_isolation_inventory_is_exact_and_governed():
    paths = contract()["forbidden_shared_paths"]
    assert len(paths) == 10
    assert {x["source"].split("-")[1] for x in paths} == {"odoo", "n8n"}
    assert all(x["replacement"].startswith("codestra-provider-") for x in paths)
    assert all(x["remove"] for x in paths)

    deployment = ROOT / "deploy/architecture-remediation"
    for name in ("email", "sms", "voice"):
        assert f"codestra-provider-{name}" in "\n".join(
            path.read_text() for path in deployment.glob("*.yaml")
        )


def test_every_runtime_endpoint_override_has_governed_compose_source():
    deployment = ROOT / "deploy/architecture-remediation"
    rendered = "\n".join(path.read_text() for path in deployment.glob("*.yaml"))
    for item in contract()["endpoint_overrides"]:
        assert f'{item["variable"]}: {item["value"]}' in rendered


def test_connector_registry_consensus():
    registry = yaml.safe_load((ROOT / "config/integration-registries.yaml").read_text())
    registered = {x["connector_id"]: x for x in registry["connectors"]}
    owners = contract()["provider_owners"]
    assert registered["mw-klyrow-v1"]["private_endpoint"] == owners["klyrow"]["private_address"]
    assert registered["mw-telnexa-v1"]["private_endpoint"] == owners["telnexa"]["private_address"]
    assert registered["mw-vicidial-v1"]["private_endpoint"] == owners["vicidial"]["private_address"]


def test_runtime_scanner_policy_consensus():
    policy = yaml.safe_load((ROOT / "config/integration-policy.yaml").read_text())
    rules = {x["variable_pattern"]: set(x["allowed"]) for x in policy["runtime"]["connector_destination_rules"]}
    assert "10.40.0.4" in rules["KLYROW.*(URL|HOST)"]
    assert "10.40.0.4" in rules["TELNEXA.*(URL|HOST)"]
    assert "10.40.0.2" in rules["VICIDIAL.*(URL|HOST)"]
