import json
import asyncio

import pytest

from control_plane_service import worker
from control_plane_service.core import Store, validate_envelope


EVENT_ID = "11111111-1111-4111-8111-111111111111"
CORRELATION_ID = "22222222-2222-4222-8222-222222222222"


def calling_event() -> dict:
    occurred_at = "2026-09-06T12:00:00Z"
    event_type = "telephony.call.ringing.v1"
    return validate_envelope({
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": occurred_at,
        "tenant_id": "tenant-a",
        "correlation_id": CORRELATION_ID,
        "idempotency_key": "calling-event-1",
        "payload": {
            "event_id": EVENT_ID,
            "schema_version": 1,
            "type": event_type,
            "tenant_id": "tenant-a",
            "business_unit_id": "unit-a",
            "campaign_id": "campaign-a",
            "agent_id": "agent-a",
            "operation_id": "33333333-3333-4333-8333-333333333333",
            "correlation_id": CORRELATION_ID,
            "occurred_at": occurred_at,
            "sequence": 1,
        },
    }, "vicidial", EVENT_ID)


def test_calling_ingress_creates_durable_realtime_delivery(tmp_path):
    current = Store(str(tmp_path / "control-plane.db"))
    current.ingest(calling_event())
    with current.connect() as db:
        targets = {row["target"] for row in db.execute(
            "SELECT target FROM event_deliveries WHERE event_id=?", (EVENT_ID,)
        )}
    assert targets == {"calling", "n8n", "odoo"}


def test_calling_delivery_is_not_exhausted_before_explicit_activation(monkeypatch, tmp_path):
    current = Store(str(tmp_path / "control-plane.db"))
    current.ingest(calling_event())
    monkeypatch.setattr(worker, "store", lambda: current)
    monkeypatch.setenv("CONTROL_PLANE_OUTBOUND_ENABLED", "true")
    monkeypatch.delenv("REALTIME_EVENT_DELIVERY_ENABLED", raising=False)
    worker.once()
    with current.connect() as db:
        delivery = db.execute(
            "SELECT state,attempts FROM event_deliveries WHERE event_id=? AND target='calling'",
            (EVENT_ID,),
        ).fetchone()
    assert dict(delivery) == {"state": "queued", "attempts": 0}


def test_calling_publisher_uses_exact_subject_identity_and_dedup_header(monkeypatch):
    published = {}

    class JetStream:
        async def publish(self, subject, payload, headers):
            published.update(subject=subject, payload=json.loads(payload), headers=headers)

    class Client:
        def jetstream(self):
            return JetStream()

        async def close(self):
            published["closed"] = True

    async def connect(**kwargs):
        published["connection"] = kwargs
        return Client()

    monkeypatch.setattr(worker.nats, "connect", connect)
    monkeypatch.setenv("REALTIME_NATS_PUBLISH_CREDENTIALS_FILE", "/run/secrets/publish.creds")
    monkeypatch.setenv("CALLING_CONTRACT_DIGEST", "a" * 64)
    asyncio.run(worker._publish_calling_event(calling_event()))
    assert published["subject"] == "telephony.agent.tenant-a.campaign-a.agent-a"
    assert published["payload"]["event_id"] == EVENT_ID
    assert published["headers"] == {
        "Nats-Msg-Id": EVENT_ID,
        "Codestra-Contract-Digest": "a" * 64,
    }
    assert published["connection"]["user_credentials"] == "/run/secrets/publish.creds"
    assert published["closed"] is True


def test_calling_publisher_rejects_subject_injection(monkeypatch):
    envelope = calling_event()
    envelope["payload"]["agent_id"] = "agent.*"
    monkeypatch.setenv("REALTIME_NATS_PUBLISH_CREDENTIALS_FILE", "/run/secrets/publish.creds")
    monkeypatch.setenv("CALLING_CONTRACT_DIGEST", "a" * 64)
    with pytest.raises(RuntimeError, match="calling_publication_subject_rejected"):
        asyncio.run(worker._publish_calling_event(envelope))


def test_calling_delivery_is_claimable_and_registration_preserves_pause(tmp_path):
    from control_plane_service.leasing import claim_event_deliveries
    current = Store(str(tmp_path / 'control-plane.db'))
    current.ingest(calling_event())
    claimed = claim_event_deliveries(current)
    assert 'calling' in {row['target'] for row in claimed}
    with current.connect() as db:
        db.execute("UPDATE integrations SET paused=1 WHERE name='calling'")
    current.initialize()
    with current.connect() as db:
        assert db.execute("SELECT paused FROM integrations WHERE name='calling'").fetchone()['paused'] == 1
        assert db.execute("SELECT COUNT(*) AS n FROM circuits WHERE name='calling'").fetchone()['n'] == 1


def test_realtime_request_and_response_match_canonical_schema():
    from pathlib import Path
    import yaml
    root=Path(__file__).parents[1]
    api=yaml.safe_load((root/'docs/openapi/control-plane-v1.yaml').read_text())
    canonical=yaml.safe_load((root/'contracts/telephony/codestra-calling-api.v1.openapi.yaml').read_text())
    path=api['paths']['/api/v1/realtime/sessions']['post']
    request=path['requestBody']['content']['application/json']['schema']
    response=path['responses']['201']['content']['application/json']['schema']
    expected=canonical['components']['schemas']['RealtimeSession']
    assert set(request['required'])=={'campaign_id'}
    assert 'resume_cursor' in request['properties'] and 'agent_id' not in request['properties']
    assert response['required']==expected['required']
    for key in expected['required']:
        if 'type' in expected['properties'][key]:
            assert response['properties'][key]['type']==expected['properties'][key]['type']
    assert response['properties']['websocket_url']['enum']==[expected['properties']['websocket_url']['const']]
