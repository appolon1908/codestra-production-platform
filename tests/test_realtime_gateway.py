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


@pytest.mark.parametrize('mismatch', ['tenant_id', 'campaign_id', 'agent_id', 'digest',
                                     'subject', 'schema_version', 'sequence', 'cursor', 'json'])
def test_mismatched_nats_event_never_reaches_socket(monkeypatch, mismatch):
    import asyncio
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    claims = dict(tenant_id='tenant-a', campaign_id='campaign-a', agent_id='agent-a',
                  authenticated_subject='subject-a')
    event = {**claims, 'schema_version': 1, 'sequence': 2}
    subject = 'telephony.agent.tenant-a.campaign-a.agent-a'
    message = SimpleNamespace(subject=subject, headers={'Codestra-Contract-Digest': 'a' * 64},
                              metadata=SimpleNamespace(sequence=SimpleNamespace(stream=19)), ack=AsyncMock())
    if mismatch in ('tenant_id', 'campaign_id', 'agent_id'):
        event[mismatch] = 'other'
    elif mismatch == 'digest': message.headers['Codestra-Contract-Digest'] = 'b' * 64
    elif mismatch == 'subject': message.subject = 'telephony.agent.other.campaign-a.agent-a'
    elif mismatch == 'cursor': message.metadata.sequence.stream = True
    elif mismatch in ('schema_version', 'sequence'): event[mismatch] = True
    message.data = b'[]' if mismatch == 'json' else json.dumps(event).encode()
    subscription = SimpleNamespace(next_msg=AsyncMock(return_value=message))
    jetstream = SimpleNamespace(subscribe=AsyncMock(return_value=subscription))
    client = SimpleNamespace(jetstream=lambda: jetstream, close=AsyncMock())
    socket = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
    monkeypatch.setenv('REALTIME_EVENT_DELIVERY_ENABLED', 'true')
    monkeypatch.setenv('REALTIME_NATS_CREDENTIALS_FILE', '/synthetic/test-only')
    monkeypatch.setenv('CALLING_CONTRACT_DIGEST', 'a' * 64)
    monkeypatch.setattr(realtime_gateway.nats, 'connect', AsyncMock(return_value=client))
    monkeypatch.setattr(realtime_gateway, 'authorized_agent_membership', lambda *args: True)
    asyncio.run(realtime_gateway.forward_agent_events(socket, claims))
    socket.send.assert_not_called()
    socket.close.assert_awaited_once_with(code=4403, reason='realtime_event_rejected')
    message.ack.assert_not_called()
    client.close.assert_awaited_once()


def test_bound_event_preserves_operation_sequence_and_stream_cursor(monkeypatch):
    import json
    from types import SimpleNamespace
    claims = dict(tenant_id='tenant-a', campaign_id='campaign-a', agent_id='agent-a')
    event = {**claims, 'schema_version': 1, 'sequence': 2}
    subject = 'telephony.agent.tenant-a.campaign-a.agent-a'
    monkeypatch.setenv('CALLING_CONTRACT_DIGEST', 'a' * 64)
    message = SimpleNamespace(subject=subject, headers={'Codestra-Contract-Digest': 'a' * 64},
        data=json.dumps(event).encode(), metadata=SimpleNamespace(sequence=SimpleNamespace(stream=19)))
    assert realtime_gateway.validate_realtime_delivery(message, claims, subject) == {'cursor': 19, 'event': event}


@pytest.mark.parametrize("raw,code", [
    ('[]', 4403), ('null', 4403), ('true', 4403), ('42', 4403),
    ('{"type":"command"}', 4403), ('{"type":"ping","command":"start"}', 4403),
    ('{"type":"command","type":"ping"}', 4400), (b"\xff", 4400),
])
def test_invalid_socket_message_is_rejected_without_transport_error(monkeypatch, raw, code):
    import asyncio
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    class Socket:
        request = SimpleNamespace(headers={"Sec-WebSocket-Protocol": "session.test"})
        send = AsyncMock()
        close = AsyncMock()

        async def messages(self):
            yield raw

        def __aiter__(self):
            return self.messages()

    async def idle_events(*args):
        await asyncio.Event().wait()

    socket = Socket()
    monkeypatch.setattr(realtime_gateway, "consume_token", lambda _: dict(
        tenant_id="tenant-a", agent_id="agent-a", campaign_id="campaign-a"))
    monkeypatch.setattr(realtime_gateway, "forward_agent_events", idle_events)
    asyncio.run(realtime_gateway.agent_socket(socket))
    assert socket.close.await_args.kwargs["code"] == code
    socket.close.assert_awaited_once()
    assert [json.loads(call.args[0])["event_type"] for call in socket.send.await_args_list] == ["agent.session.ready"]


@pytest.mark.parametrize("cursor", [None, 0, 19])
def test_replay_policy_and_revoked_authorization_prevent_delivery(monkeypatch, cursor):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    claims = dict(tenant_id="tenant-a", agent_id="agent-a", campaign_id="campaign-a",
                  authenticated_subject="subject-a", resume_cursor=cursor)
    subscription = SimpleNamespace(next_msg=AsyncMock())
    jetstream = SimpleNamespace(subscribe=AsyncMock(return_value=subscription))
    client = SimpleNamespace(jetstream=lambda: jetstream, close=AsyncMock())
    socket = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
    monkeypatch.setenv("REALTIME_EVENT_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("REALTIME_NATS_CREDENTIALS_FILE", "/synthetic/test-only")
    monkeypatch.setattr(realtime_gateway.nats, "connect", AsyncMock(return_value=client))
    monkeypatch.setattr(realtime_gateway, "authorized_agent_membership", lambda *args: False)
    asyncio.run(realtime_gateway.forward_agent_events(socket, claims))
    options = jetstream.subscribe.await_args.kwargs
    if cursor is None:
        assert options["deliver_policy"] == realtime_gateway.nats_api.DeliverPolicy.NEW
        assert "opt_start_seq" not in options
    else:
        assert options["deliver_policy"] == realtime_gateway.nats_api.DeliverPolicy.BY_START_SEQUENCE
        assert options["opt_start_seq"] == cursor + 1
    subscription.next_msg.assert_not_called()
    socket.send.assert_not_called()
    socket.close.assert_awaited_once_with(code=4403, reason="realtime_authorization_revoked")
    client.close.assert_awaited_once()
