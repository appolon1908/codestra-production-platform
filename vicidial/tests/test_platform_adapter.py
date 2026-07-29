from __future__ import annotations

import time
from pathlib import Path
from typing import ClassVar

import pytest
from codestra_vicidial.platform_api import platform_router
from codestra_vicidial.platform_models import (
    ExecutionGrantClaims,
    InternalCallRequest,
    VicidialUserRequest,
)
from codestra_vicidial.platform_security import (
    ExecutionGrantVerifier,
    ServiceIdentity,
    TokenDenied,
)
from codestra_vicidial.platform_service import (
    LocalTelephonyBackend,
    PlatformAdapterService,
    PlatformFlags,
    PlatformPolicyDenied,
)
from codestra_vicidial.state import StateStore
from fastapi import FastAPI
from fastapi.testclient import TestClient

HASH = "sha256:" + "a" * 64
FLAG_HASH = "sha256:" + "b" * 64


class Reporter:
    def __init__(self):
        self.events: list[tuple] = []

    def register(self, operation, action):
        self.events.append(("register", operation.operation_public_id, action))

    def transition(self, operation, sequence, state):
        self.events.append(("transition", sequence, state))

    def terminal(self, operation, result):
        self.events.append(("terminal", result["result_hash"]))


class Tokens:
    scopes: ClassVar[set[str]] = {
        "telephony.read",
        "telephony.vicidial.users.apply",
        "monitor.read",
        "service.attest",
        "metrics.read",
        "telephony.policy.evaluate",
    }

    def verify(self, token: str, required_scope: str) -> ServiceIdentity:
        if token != "valid" or required_scope not in self.scopes:
            raise TokenDenied("denied")
        return ServiceIdentity("codestra-middleware", frozenset(self.scopes))


def request_values() -> dict:
    return {
        "operation_public_id": "OPR-test-001",
        "command_public_id": "CMD-test-001",
        "target_public_id": "AGT-test-001",
        "environment": "staging",
        "business_unit_public_id": "BU-test-001",
        "campaign_public_id": "CMP-test-001",
        "allocation_reservation_public_id": "RSV-test-001",
        "allocation_reservation_generation": 1,
        "desired_state_version": 1,
        "desired_state_hash": HASH,
        "policy_hash": HASH,
        "feature_flag_snapshot_hash": FLAG_HASH,
        "middleware_action_enabled": True,
        "correlation_id": "COR-test-001",
        "idempotency_key": "IDM-test-001",
    }


def signed_user(grants: ExecutionGrantVerifier, *, maximum_actions: int = 1):
    now = int(time.time())
    values = request_values()
    claims = ExecutionGrantClaims(
        grant_id="GRT-test-001",
        command_id=values["command_public_id"],
        operation_id=values["operation_public_id"],
        environment="staging",
        business_unit_public_id=values["business_unit_public_id"],
        campaign_public_id=values["campaign_public_id"],
        target_public_id=values["target_public_id"],
        action="telephony.vicidial.user.apply",
        desired_state_version=1,
        allocation_reservation_public_id=values[
            "allocation_reservation_public_id"
        ],
        idempotency_key=values["idempotency_key"],
        policy_hash=HASH,
        feature_flag_snapshot_hash=FLAG_HASH,
        middleware_action_enabled=True,
        issued_at=now - 1,
        expires_at=now + 120,
        maximum_actions=maximum_actions,
    )
    return VicidialUserRequest(
        **values,
        execution_grant=grants.issue(claims),
        agent_public_id="AGT-test-001",
        user_group="TEST_GROUP",
        state="DISABLED",
    )


def service(tmp_path: Path, flags: PlatformFlags):
    state = StateStore(tmp_path / "state.sqlite3")
    grants = ExecutionGrantVerifier(b"unit-test-execution-grant-key", state)
    reporter = Reporter()
    adapter = PlatformAdapterService(
        state,
        flags,
        grants,
        LocalTelephonyBackend(tmp_path / "asterisk"),
        resource_allowlist=frozenset({"AGT-test-001"}),
        reporter=reporter,
    )
    return adapter, grants, reporter


def enabled_user_flags() -> PlatformFlags:
    return PlatformFlags(
        adapter_api_enabled=True,
        vicidial_reads_enabled=True,
        vicidial_user_writes_enabled=True,
        local_kill_switch=False,
    )


def test_every_action_defaults_fail_closed(tmp_path):
    adapter, grants, _ = service(tmp_path, PlatformFlags())
    with pytest.raises(PlatformPolicyDenied):
        adapter.put_user(signed_user(grants))
    snapshot = adapter.effective_flags()
    assert snapshot["vicidial_user_writes_enabled"] is False
    assert snapshot["external_calls_enabled"] is False
    assert snapshot["customer_calls_enabled"] is False
    assert snapshot["transfers_enabled"] is False
    assert "local_kill_switch" not in snapshot


def test_grant_budget_auto_disables_but_exact_retry_is_idempotent(tmp_path):
    adapter, grants, reporter = service(tmp_path, enabled_user_flags())
    request = signed_user(grants)
    first = adapter.put_user(request)
    replay = adapter.put_user(request)
    assert first["auto_disabled"] is True
    assert replay["idempotent_replay"] is True
    assert adapter.state.action_budget("GRT-test-001")["consumed_actions"] == 1
    assert [event[0] for event in reporter.events] == [
        "register", "transition", "transition", "terminal"
    ]


def test_changed_payload_with_same_idempotency_key_conflicts(tmp_path):
    adapter, grants, _ = service(tmp_path, enabled_user_flags())
    request = signed_user(grants)
    adapter.put_user(request)
    with pytest.raises(ValueError, match="idempotency conflict"):
        adapter.put_user(request.model_copy(update={"user_group": "OTHER_GROUP"}))


def test_wrong_grant_target_is_rejected_before_action(tmp_path):
    adapter, grants, reporter = service(tmp_path, enabled_user_flags())
    request = signed_user(grants).model_copy(
        update={"target_public_id": "AGT-other-001"}
    )
    adapter.resource_allowlist = frozenset({"AGT-other-001"})
    with pytest.raises(TokenDenied, match="target_public_id mismatch"):
        adapter.put_user(request)
    assert reporter.events == []


def test_internal_call_rejects_unapproved_endpoints(tmp_path):
    flags = PlatformFlags(
        adapter_api_enabled=True,
        internal_calls_enabled=True,
        local_kill_switch=False,
    )
    adapter, _grants, _ = service(tmp_path, flags)
    values = request_values() | {
        "target_public_id": "CALL-test-001",
        "execution_grant": "x" * 32,
        "call_public_id": "CALL-test-001",
        "source_endpoint_public_id": "EPT-test-001",
        "destination_endpoint_public_id": "EPT-test-002",
        "maximum_duration_seconds": 120,
        "purpose": "controlled_internal_staging_acceptance",
    }
    request = InternalCallRequest(**values)
    with pytest.raises(PlatformPolicyDenied, match="not approved"):
        adapter.internal_call(request)


def test_private_api_auth_and_safe_flag_response(tmp_path):
    adapter, _, _ = service(tmp_path, enabled_user_flags())
    app = FastAPI()
    app.include_router(platform_router(adapter, Tokens()))
    client = TestClient(app)
    assert client.get("/api/v1/telephony/effective-flags").status_code == 422
    denied = client.get(
        "/api/v1/telephony/effective-flags",
        headers={"Authorization": "Bearer bad"},
    )
    assert denied.status_code == 403
    response = client.get(
        "/api/v1/telephony/effective-flags",
        headers={"Authorization": "Bearer valid"},
    )
    assert response.status_code == 200
    assert "configuration_checksum" in response.json()
    assert "local_kill_switch" not in response.json()
    assert "key" not in response.json()


def test_route_table_has_no_generic_sql_shell_file_or_raw_dialplan(tmp_path):
    adapter, _, _ = service(tmp_path, enabled_user_flags())
    app = FastAPI()
    app.include_router(platform_router(adapter, Tokens()))
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert not any(
        forbidden in path
        for path in paths
        for forbidden in ("/sql", "/shell", "/files", "/dialplan/edit")
    )
