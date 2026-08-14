import hashlib

import pytest

from integrations.effective_once import EffectiveOnceSink, IntegrationError


def event(number=1):
    payload = f"synthetic-{number}".encode()
    return {
        "event_id": f"event-{number}",
        "correlation_id": "correlation-test-syn-1",
        "idempotency_key": "test-syn-1",
        "payload_hash": hashlib.sha256(payload).hexdigest(),
        "sequence": number,
    }


@pytest.mark.parametrize("namespace", ["odoo_test", "n8n_test", "callback_test"])
def test_outage_restart_and_duplicate_are_effective_once(tmp_path, namespace) -> None:
    path = tmp_path / f"{namespace}.sqlite3"
    sink = EffectiveOnceSink(path, namespace)
    assert sink.enqueue(event()) == "accepted"
    assert sink.deliver(event(), unavailable=True) == "retry"
    sink.db.close()
    sink = EffectiveOnceSink(path, namespace)
    assert sink.deliver(event()) == "delivered"
    assert sink.enqueue(event()) == "duplicate"
    assert sink.deliver(event()) == "duplicate_suppressed"
    assert sink.counts() == (1, 1)


def test_production_namespace_is_impossible(tmp_path) -> None:
    with pytest.raises(IntegrationError, match="production namespace"):
        EffectiveOnceSink(tmp_path / "unsafe.sqlite3", "odoo_production")


def test_delivery_rejects_identity_not_durably_enqueued(tmp_path) -> None:
    sink = EffectiveOnceSink(tmp_path / "identity.sqlite3", "odoo_test")
    accepted = event()
    assert sink.enqueue(accepted) == "accepted"
    altered = {**accepted, "correlation_id": "altered"}
    with pytest.raises(IntegrationError, match="differs from durable event"):
        sink.deliver(altered)


def test_newer_state_wins_without_duplicate_effect(tmp_path) -> None:
    sink = EffectiveOnceSink(tmp_path / "ordering.sqlite3", "odoo_test")
    assert sink.enqueue(event(2)) == "accepted"
    assert sink.deliver(event(2)) == "delivered"
    assert sink.enqueue(event(1)) == "accepted"
    assert sink.deliver(event(1)) == "delivered"
    assert sink.counts() == (2, 1)


def test_equal_sequence_conflicting_effect_is_rejected(tmp_path) -> None:
    sink = EffectiveOnceSink(tmp_path / "equal-sequence.sqlite3", "odoo_test")
    first = event()
    assert sink.enqueue(first) == "accepted"
    assert sink.deliver(first) == "delivered"
    conflicting = {**event(2), "idempotency_key": first["idempotency_key"], "sequence": first["sequence"]}
    assert sink.enqueue(conflicting) == "accepted"
    with pytest.raises(IntegrationError, match="equal-sequence effect identity conflicts"):
        sink.deliver(conflicting)
