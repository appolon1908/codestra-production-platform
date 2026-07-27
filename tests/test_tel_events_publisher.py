import json
import os
import stat
import tempfile

import pytest

from tel_events.publisher import (
    Cursor,
    DeliveryLedger,
    PublisherError,
    SourceBoundary,
    build_call_ended_event,
    select_finalized_rows,
    wire_event,
)


def row(source="1.2", end=2000, **extra):
    value = {
        "uniqueid": source,
        "end_epoch": end,
        "length_in_sec": 30,
        "status": "SALE",
        "campaign_id": "C1",
        "user_group": "TL",
        "phone_number": "must-not-leak",
    }
    value.update(extra)
    return value


def test_composite_cursor_and_boundary_are_strict():
    boundary = SourceBoundary("vicidial_log", 1500, Cursor(2000, "1.1"))
    chosen = select_finalized_rows(
        [row("old", 1499), row("1.1", 2000), row("1.2", 2000), row("1.3", 2001)],
        boundary,
    )
    assert [item["uniqueid"] for item in chosen] == ["1.2", "1.3"]


def test_event_is_minimized_and_deterministic():
    first = build_call_ended_event(row(), "vicidial_log")
    second = build_call_ended_event(row(), "vicidial_log")
    assert first == second
    assert "phone_number" not in json.dumps(first)
    assert set(first["payload"]) <= {
        "call_id", "ended_at", "duration_seconds", "direction",
        "disposition_code", "campaign_reference", "business_unit_reference",
    }
    assert first["test_syn"] is False
    assert "_cursor" not in wire_event(first)
    assert "idempotency_key" not in wire_event(first)


@pytest.mark.parametrize("bad", [None, 0, -1, True, "2000"])
def test_invalid_finalization_rejected(bad):
    with pytest.raises(PublisherError):
        build_call_ended_event(row(end=bad), "vicidial_log")


def test_ack_retry_and_dead_letter_cursor_advance_only_on_ack():
    with tempfile.TemporaryDirectory() as directory:
        ledger = DeliveryLedger(os.path.join(directory, "ledger.sqlite"), max_attempts=2)
        event = build_call_ended_event(row("a", 2001), "vicidial_log")
        ledger.stage(event)
        assert ledger.acknowledge(event["event_id"], 503) == "retry"
        assert ledger.state(event["event_id"]) == "retry"
        assert ledger.acknowledge(event["event_id"], 202) == "acknowledged"
        assert ledger.state(event["event_id"]) == "acknowledged"
        dead = build_call_ended_event(row("b", 2002), "vicidial_log")
        ledger.stage(dead)
        assert ledger.acknowledge(dead["event_id"], 500) == "retry"
        assert ledger.acknowledge(dead["event_id"], 500) == "dead_letter"
        report = ledger.reconcile()
        assert report["status"] == "healthy"
        assert report["sources"]["vicidial_log"]["acknowledged"] == 1
        assert report["sources"]["vicidial_log"]["dead_letter"] == 1
        ledger.close()


def test_watermark_permission_and_schema():
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as handle:
        json.dump({
            "ordering": ["end_epoch", "stable_source_id"],
            "captured_at": "2026-07-25T11:24:19Z",
            "sources": {
                "vicidial_log": {"end_epoch": 1, "source_id": "a"},
                "vicidial_closer_log": {"end_epoch": 1, "source_id": "0"},
            },
        }, handle)
        path = handle.name
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        from tel_events.publisher import load_watermark
        assert len(load_watermark(path)) == 2
    finally:
        os.unlink(path)
