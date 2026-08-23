import os
from pathlib import Path

import pytest

pytest.importorskip("websockets")

from control_plane_service.core import Store
from control_plane_service import realtime_gateway


ROOT = Path(__file__).resolve().parents[1]


def test_one_time_realtime_session_token_is_bound_and_replay_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-only-realtime-secret-that-is-long-enough")
    realtime_gateway.STORE = Store(str(tmp_path / "control-plane.db"))
    token, expires = realtime_gateway.issue_token("tenant-a", "agent-7", "campaign-4", "crm-ui")
    assert expires > 0
    claims = realtime_gateway.consume_token(token)
    assert claims["tenant_id"] == "tenant-a"
    assert claims["agent_id"] == "agent-7"
    assert claims["campaign_id"] == "campaign-4"
    with pytest.raises(ValueError, match="replayed_or_unknown"):
        realtime_gateway.consume_token(token)


def test_realtime_gateway_has_bounded_transport_defaults():
    source = open("control_plane_service/realtime_gateway.py", encoding="utf-8").read()
    for value in ("max_size=65536", "max_queue=16", "ping_interval=20", "ping_timeout=10"):
        assert value in source
    assert "origins=[\"https://crm.codestra.co\"]" in source
    assert 'subprotocols=["codestra-agent-v1"]' in source
    assert 'parse_qs(parsed.query)' not in source
    assert "active_agent_membership_required" in source
    assert "ai.system='KEYCLOAK'" in source


def test_realtime_compose_declares_every_secret_and_network():
    compose = (ROOT / "deploy/control-plane/compose.realtime.yaml").read_text()
    assert "control_plane_database_url:" in compose
    assert "realtime_token_secret:" in compose
    assert "kong_gateway_secret:" in compose
    assert "name: codestra_edge" in compose
    assert "name: codestra_backend" in compose
