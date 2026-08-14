from __future__ import annotations

import hashlib
import json

import pytest

from eventing.contract import ContractError, DurableEventHarness, load_contract


def event(event_id: str = "evt-1", key: str = "logical-call-1", payload=None):
    payload = payload or {"state": "answered"}
    return {
        "event_id": event_id,
        "correlation_id": "corr-1",
        "tenant_id": "synthetic-tenant",
        "campaign_id": "TEST_SYN",
        "event_type": "call.state",
        "schema_version": 1,
        "producer": "isolated-fixture",
        "created_at": "2026-08-14T17:00:00Z",
        "idempotency_key": key,
        "trace_context": "00-00000000000000000000000000000001-0000000000000001-01",
        "privacy_classification": "synthetic",
        "payload_hash": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "payload": payload,
    }


def test_contract_is_durable_bounded_and_non_replaying():
    contract = load_contract()
    assert contract["historical_replay_allowed"] is False
    assert {item["name"] for item in contract["streams"]} == {
        "CODESTRA_INGRESS_V1", "CODESTRA_PROCESSING_V1", "CODESTRA_RESULTS_V1",
        "CODESTRA_CALLBACKS_V1", "CODESTRA_RETRY_V1", "CODESTRA_DEAD_LETTER_V1",
    }
    assert all(item["ack_policy"] == "explicit" for item in contract["consumers"])
    assert {item["deliver_policy"] for item in contract["consumers"]} == {"all", "new"}


def test_duplicate_and_conflicting_delivery(tmp_path):
    harness = DurableEventHarness(tmp_path / "events.sqlite")
    value = event()
    assert harness.ingest(value, 1) == "accepted"
    assert harness.ingest(value, 1) == "duplicate"
    conflict = event(payload={"state": "ended"})
    with pytest.raises(ContractError, match="conflicting"):
        harness.ingest(conflict, 2)
    assert harness.process("evt-1") == "acknowledged"
    assert harness.process("evt-1") == "acknowledged"
    assert harness.counts() == {"event_inbox": 1, "business_effect": 1, "dead_letter": 0}


def test_restart_after_commit_and_publish_is_effectively_once(tmp_path):
    path = tmp_path / "events.sqlite"
    first = DurableEventHarness(path)
    assert first.ingest(event(), 1) == "accepted"
    first.close()
    restarted = DurableEventHarness(path)
    assert restarted.process("evt-1") == "acknowledged"
    restarted.close()
    again = DurableEventHarness(path)
    assert again.process("evt-1") == "acknowledged"
    assert again.counts()["business_effect"] == 1


def test_ack_timeout_exhaustion_moves_once_to_dead_letter(tmp_path):
    harness = DurableEventHarness(tmp_path / "events.sqlite", max_deliver=3)
    harness.ingest(event(), 1)
    assert harness.process("evt-1", fail=True) == "retry"
    assert harness.process("evt-1", fail=True) == "retry"
    assert harness.process("evt-1", fail=True) == "dead_letter"
    assert harness.process("evt-1", fail=True) == "dead_letter"
    assert harness.counts() == {"event_inbox": 1, "business_effect": 0, "dead_letter": 1}


def test_out_of_order_terminal_state_cannot_regress(tmp_path):
    harness = DurableEventHarness(tmp_path / "events.sqlite")
    newer = event("evt-new", "logical-call-new", {"state": "ended"})
    older = event("evt-old", "logical-call-old", {"state": "answered"})
    harness.ingest(newer, 20)
    harness.ingest(older, 10)
    harness.process("evt-new")
    harness.process("evt-old")
    row = harness.connection.execute(
        "SELECT event_id,terminal_sequence FROM business_effect WHERE correlation_id='corr-1'"
    ).fetchone()
    assert row == ("evt-new", 20)
    assert harness.counts()["business_effect"] == 1


def test_event_validation_rejects_wrong_schema_and_payload_hash(tmp_path):
    harness = DurableEventHarness(tmp_path / "events.sqlite")
    wrong_schema = event()
    wrong_schema["schema_version"] = 2
    with pytest.raises(ContractError, match="schema"):
        harness.ingest(wrong_schema, 1)
    wrong_hash = event()
    wrong_hash["payload_hash"] = "0" * 64
    with pytest.raises(ContractError, match="payload hash"):
        harness.ingest(wrong_hash, 1)
