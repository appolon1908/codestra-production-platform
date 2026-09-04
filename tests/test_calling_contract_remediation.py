from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_command_dispatch_requires_all_applicable_activation_gates() -> None:
    api = load_yaml("contracts/telephony/codestra-calling-api.v1.openapi.yaml")
    ecosystem = load_yaml("contracts/telephony/codestra-calling-ecosystem.v1.yaml")
    gate = api["paths"]["/v1/telephony/commands"]["post"]["x-codestra-dispatch-preconditions"]
    assert gate["all_applicable_gates_must_be_true"] is True
    assert gate["external_effect_on_denial"] is False
    assert gate["calls_placed_delta_on_denial"] == 0
    configured = set(ecosystem["activation_defaults"])
    mapped = {item for values in gate["command_gate_matrix"].values() for item in values}
    mapped.add(gate["administrative_reconciliation_gate"])
    assert mapped == configured
    assert all(value is False for value in ecosystem["activation_defaults"].values())


def test_realtime_ticket_claims_are_server_derived() -> None:
    api = load_yaml("contracts/telephony/codestra-calling-api.v1.openapi.yaml")
    session = api["paths"]["/api/v1/realtime/sessions"]["post"]
    request = api["components"]["schemas"]["RealtimeSessionRequest"]
    assert request["required"] == ["campaign_id"]
    assert set(request["properties"]) == {"campaign_id", "resume_cursor"}
    authority = session["x-codestra-authorization"]
    assert authority["client_supplied_identity_claims"] == "forbidden"
    assert "server-side" in authority["ticket_claims_source"]


def test_subject_forming_ids_reject_wildcards_and_separators() -> None:
    api = load_yaml("contracts/telephony/codestra-calling-api.v1.openapi.yaml")
    events = load_yaml("contracts/telephony/codestra-calling-events.v1.asyncapi.yaml")
    pattern = re.compile(api["components"]["schemas"]["NatsSubjectToken"]["pattern"])
    for valid in ("tenant_1", "campaign-2", "Agent03"):
        assert pattern.fullmatch(valid)
    for invalid in ("tenant.one", "*", ">", "agent 1", "a/b", ""):
        assert not pattern.fullmatch(invalid)
    properties = events["components"]["schemas"]["CallingEvent"]["properties"]
    for field in ("tenant_id", "campaign_id", "agent_id"):
        assert properties[field]["$ref"].endswith("/NatsSubjectToken")


def test_public_edge_blocks_internal_service_paths() -> None:
    caddy = (ROOT / "operations/caddy/api.codestra.co.caddy").read_text(encoding="utf-8")
    deny = "handle /internal* {"
    assert deny in caddy
    assert re.search(r"handle /internal\* \{\s*respond 404\s*\}", caddy)
    assert caddy.index(deny) < caddy.index("@realtime path")
    assert caddy.index(deny) < caddy.index("\thandle {\n")


def test_active_session_authorization_is_bounded_and_fail_closed() -> None:
    api = load_yaml("contracts/telephony/codestra-calling-api.v1.openapi.yaml")
    events = load_yaml("contracts/telephony/codestra-calling-events.v1.asyncapi.yaml")
    ecosystem = load_yaml("contracts/telephony/codestra-calling-ecosystem.v1.yaml")
    operation = api["paths"]["/internal/v1/realtime/authorizations/revalidate"]["post"]
    policy = operation["x-codestra-failure-policy"]
    assert policy["maximum_authorization_age_seconds"] <= 30
    assert policy["maximum_disconnect_delay_seconds"] <= 30
    assert policy["delivery_during_revalidation_failure"] == "forbidden"
    delivery = events["x-codestra-delivery"]
    assert delivery["authorization_revalidation_interval_seconds"] <= 30
    assert delivery["authorization_loss_max_disconnect_seconds"] <= 30
    lifecycle = ecosystem["realtime"]["authorization"]
    assert lifecycle["revalidation_interval_seconds"] <= 30
    assert lifecycle["maximum_disconnect_delay_seconds"] <= 30
    assert lifecycle["reconnect_requires_new_ticket"] is True


def test_required_platform_source_gate_covers_contracts_and_regression() -> None:
    workflow = (ROOT / ".github/workflows/platform-source-gate.yml").read_text(encoding="utf-8")
    assert '      - "contracts/telephony/**"' in workflow
    assert "Verify canonical calling contract in required validation" in workflow
    assert "tests/test_calling_contract_remediation.py" in workflow
