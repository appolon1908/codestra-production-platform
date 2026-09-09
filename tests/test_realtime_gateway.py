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
    token, expires = realtime_gateway.issue_token(
        "tenant-a", "agent-7", "campaign-4", "crm-ui", "keycloak-subject-7"
    )
    assert expires > 0
    claims = realtime_gateway.consume_token(token)
    assert claims["tenant_id"] == "tenant-a"
    assert claims["agent_id"] == "agent-7"
    assert claims["campaign_id"] == "campaign-4"
    assert claims["authenticated_subject"] == "keycloak-subject-7"
    with pytest.raises(ValueError, match="replayed_or_unknown"):
        realtime_gateway.consume_token(token)


def test_realtime_session_creation_replays_one_original_nonce(monkeypatch, tmp_path):
    monkeypatch.setenv("CALLING_CONTRACT_DIGEST", "a" * 64)
    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-only-realtime-secret-that-is-long-enough")
    realtime_gateway.STORE = Store(str(tmp_path / "control-plane.db"))
    first = realtime_gateway.issue_idempotent_session(
        "tenant-a", "agent-7", "campaign-4", "crm-ui", "keycloak-subject-7",
        "session-request-1", 12
    )
    replay = realtime_gateway.issue_idempotent_session(
        "tenant-a", "agent-7", "campaign-4", "crm-ui", "keycloak-subject-7",
        "session-request-1", 12
    )
    assert replay == first
    with realtime_gateway.STORE.connect() as db:
        assert db.execute("SELECT count(*) AS n FROM realtime_session_nonce").fetchone()["n"] == 1
    with pytest.raises(ValueError, match="idempotency_conflict"):
        realtime_gateway.issue_idempotent_session(
            "tenant-a", "agent-7", "other-campaign", "crm-ui", "keycloak-subject-7",
            "session-request-1", 12
        )


def test_realtime_gateway_has_bounded_transport_defaults():
    source = open("control_plane_service/realtime_gateway.py", encoding="utf-8").read()
    for value in ("max_size=65536", "max_queue=16", "ping_interval=20", "ping_timeout=10"):
        assert value in source
    assert "origins=[\"https://crm.codestra.co\"]" in source
    assert 'subprotocols=["codestra-agent-v1"]' in source
    assert 'parse_qs(parsed.query)' not in source
    assert "active_agent_membership_required" in source
    assert "ai.system='KEYCLOAK'" in source
    assert "resolve_agent_membership" in source
    assert "forward_agent_events" in source
    assert "REALTIME_EVENT_DELIVERY_ENABLED" in source
    assert "opt_start_seq" in source
    assert "authorized_agent_membership" in source


def test_realtime_compose_declares_every_secret_and_network():
    compose = (ROOT / "deploy/control-plane/compose.realtime.yaml").read_text()
    assert "control_plane_database_url:" in compose
    assert "realtime_token_secret:" in compose
    assert "kong_gateway_secret:" in compose
    assert 'REALTIME_EVENT_DELIVERY_ENABLED: "false"' in compose
    assert "realtime_nats_credentials:" not in compose
    enabled = (ROOT / "deploy/control-plane/compose.realtime-events-enabled.yaml").read_text()
    assert 'REALTIME_EVENT_DELIVERY_ENABLED: "true"' in enabled
    assert "realtime_nats_credentials:" in enabled
    assert '"127.0.0.1:18103:18103"' in compose
    assert "name: codestra_edge" in compose
    assert "name: codestra_backend" in compose


@pytest.mark.parametrize('value', [None, [], True, 'campaign',
    {'campaign_id': None}, {'campaign_id': 123}, {'campaign_id': 'a.b'},
    {'campaign_id': 'a', 'tenant_id': 'other'}, {'campaign_id': 'a', 'resume_cursor': True},
    {'campaign_id': 'a', 'resume_cursor': -1}, {'campaign_id': 'a', 'resume_cursor': 1.5},
    {'campaign_id': 'a', 'resume_cursor': 2**64 - 1}, {'campaign_id': 'a' * 129}])
def test_session_request_rejects_invalid_scope_and_cursor(value):
    with pytest.raises(ValueError):
        realtime_gateway.validate_session_request(value)


def test_session_request_accepts_canonical_scope_and_bounded_cursor():
    assert realtime_gateway.validate_session_request({'campaign_id': 'campaign-1'}) == ('campaign-1', None)
    assert realtime_gateway.validate_session_request({'campaign_id': 'campaign-1', 'resume_cursor': 0}) == ('campaign-1', 0)


def test_duplicate_session_fields_rejected():
    import json
    with pytest.raises(ValueError, match='duplicate_request_field'):
        json.loads('{"campaign_id":"one","campaign_id":"two"}',
                   object_pairs_hook=realtime_gateway.session_json_object)


@pytest.mark.parametrize('raw', [b'[]', b'null', b'{"campaign_id":false}',
    b'{"campaign_id":"a","resume_cursor":true}',
    b'{"campaign_id":"a","campaign_id":"b"}', b'\xff'])
def test_invalid_http_session_body_never_queries_membership(monkeypatch, raw):
    from io import BytesIO
    from unittest.mock import Mock
    handler = object.__new__(realtime_gateway.SessionHandler)
    handler.path = '/api/v1/realtime/sessions'
    handler.headers = {'X-Codestra-Gateway-Secret': 'synthetic-gateway',
        'X-Authenticated-Tenant': 'tenant', 'X-Authenticated-Client': 'client',
        'X-Authenticated-Subject': 'subject', 'Idempotency-Key': 'request-1',
        'Content-Length': str(len(raw))}
    handler.rfile = BytesIO(raw)
    handler._json = Mock()
    membership = Mock()
    monkeypatch.setattr(realtime_gateway, '_read_secret', lambda _: 'synthetic-gateway')
    monkeypatch.setattr(realtime_gateway, 'resolve_agent_membership', membership)
    handler.do_POST()
    handler._json.assert_called_once_with(422, {'error': 'invalid_session_request'})
    membership.assert_not_called()
