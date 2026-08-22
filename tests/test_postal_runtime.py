import sqlite3

import pytest

from control_plane_service.core import ControlPlaneError
from control_plane_service.postal_runtime import PostalInbox


class Adapter:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def ingest(self, **value):
        self.calls += 1
        if self.fail:
            raise ControlPlaneError("projection_unavailable")
        return {
            "tenant_id": value["tenant_id"], "campaign_id": "campaign-1",
            "agent_id": "agent-1", "mailbox_id": "mailbox-1",
            "message_id": "<message@example.test>",
            "correlation_id": value["correlation_id"],
        }


def run(inbox, adapter, **overrides):
    value = {
        "tenant_id": "tenant-1", "provider_event_id": "postal-1",
        "correlation_id": "correlation-1", "recipient": "agent@example.test",
        "raw_message": b"Message-ID: <message@example.test>\r\n\r\nhello",
        "adapter": adapter,
    }
    value.update(overrides)
    return inbox.run(**value)


def test_completed_event_replays_stored_result_without_downstream_call(tmp_path):
    inbox = PostalInbox(str(tmp_path / "postal.db")); adapter = Adapter()
    first, duplicate = run(inbox, adapter)
    second, replay = run(inbox, adapter)
    assert duplicate is False and replay is True
    assert first == second and adapter.calls == 1


def test_event_id_cannot_be_reused_for_different_content_or_tenant(tmp_path):
    inbox = PostalInbox(str(tmp_path / "postal.db")); adapter = Adapter()
    run(inbox, adapter)
    with pytest.raises(ControlPlaneError, match="inbound_idempotency_conflict"):
        run(inbox, adapter, raw_message=b"Message-ID: <changed@example.test>\r\n\r\nchanged")
    with pytest.raises(ControlPlaneError, match="inbound_idempotency_conflict"):
        run(inbox, adapter, tenant_id="tenant-2")


def test_failed_event_is_retryable_with_same_immutable_request(tmp_path):
    inbox = PostalInbox(str(tmp_path / "postal.db")); failing = Adapter(fail=True)
    with pytest.raises(ControlPlaneError, match="projection_unavailable"):
        run(inbox, failing)
    healthy = Adapter()
    result, duplicate = run(inbox, healthy)
    assert duplicate is False and result["campaign_id"] == "campaign-1"


def test_stale_processing_claim_is_recovered(tmp_path):
    path = str(tmp_path / "postal.db")
    inbox = PostalInbox(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO postal_inbound_event VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "postal-1",
                "tenant-1",
                "placeholder",
                "correlation-1",
                "PROCESSING",
                None,
                None,
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:00:00+00:00",
            ),
        )
    raw = b"Message-ID: <message@example.test>\r\n\r\nhello"
    import hashlib

    request_hash = hashlib.sha256(
        b"\0".join((b"tenant-1", b"agent@example.test", raw))
    ).hexdigest()
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE postal_inbound_event SET request_hash=? WHERE provider_event_id='postal-1'",
            (request_hash,),
        )
    result, duplicate = run(inbox, Adapter(), raw_message=raw)
    assert duplicate is False
    assert result["campaign_id"] == "campaign-1"


def test_postgres_migration_is_durable_fail_closed_contract():
    sql = open("migrations/control_plane/005_postal_inbound_inbox.sql", encoding="utf-8").read()
    assert "provider_event_id text PRIMARY KEY" in sql
    assert "CHECK(status IN ('PROCESSING','COMPLETED','FAILED'))" in sql
    assert "REVOKE ALL" in sql and "codestra_control_plane_runtime" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "current_setting('app.tenant_id',true)" in sql
