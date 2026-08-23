import time

from control_plane_service.core import Store, validate_envelope
from control_plane_service import leasing


def test_event_delivery_claim_is_exclusive_pause_aware_and_recoverable(tmp_path):
    store = Store(str(tmp_path / "control-plane.db"))
    event = validate_envelope({
        "event_type": "customer.created", "event_version": "1.0",
        "occurred_at": "2026-08-23T00:00:00Z", "tenant_id": "tenant",
        "customer_id": "customer", "correlation_id": "correlation",
        "idempotency_key": "lease-test", "payload": {"synthetic": True},
    }, "odoo", "lease-event")
    store.ingest(event)
    with store.connect() as db:
        db.execute("UPDATE integrations SET paused=1 WHERE name='odoo'")

    first = leasing.claim_event_deliveries(store)
    assert len(first) == 1
    assert first[0]["target"] == "n8n"
    assert first[0]["lease_token"]
    assert leasing.claim_event_deliveries(store) == []

    with store.connect() as db:
        db.execute("UPDATE event_deliveries SET lease_expires_at=? WHERE event_id=? AND target='n8n'",
                   (time.time() - 1, event["event_id"]))
    recovered = leasing.claim_event_deliveries(store)
    assert len(recovered) == 1
    assert recovered[0]["lease_token"] != first[0]["lease_token"]


def test_postgres_claims_use_skip_locked_and_fencing():
    source = open("control_plane_service/leasing.py", encoding="utf-8").read()
    assert "FOR UPDATE OF d SKIP LOCKED" in source
    assert "FOR UPDATE OF m SKIP LOCKED" in source
    assert "lease_owner" in source and "lease_token" in source
    assert "i.paused=0" in source
