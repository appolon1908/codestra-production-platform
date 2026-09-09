"""An orchestration retry is not a new business operation."""

import json

import pytest

from control_plane_service import automation
from control_plane_service.core import ControlPlaneError, Store


def event(attempt="exec-1"):
    return dict(
        schema_version="1",
        event_id="event-1",
        event_type="customer.created",
        correlation_id="corr-1",
        idempotency_key="business-1",
        tenant_id="tenant-a",
        business_unit_id="unit-a",
        campaign_id="campaign-a",
        entity_type="customer",
        entity_id="customer-1",
        actor_type="SYSTEM",
        actor_id="middleware",
        occurred_at="2026-09-07T00:00:00Z",
        automation_key="customer-created",
        orchestration_execution_id=attempt,
        payload={},
    )


def result(attempt="exec-1", status="COMPLETED"):
    return dict(
        event_id="event-1",
        correlation_id="corr-1",
        idempotency_key="result-" + attempt,
        workflow_key="customer-created",
        execution_id=attempt,
        status=status,
        actions=[{"type": "crm.customer.synchronize"}] if status == "COMPLETED" else [],
        completed_at="2026-09-07T00:00:01Z",
    )


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "db"))
    calls = []

    def invoke(action, value, request_hash):
        calls.append((action, request_hash))
        return {
            "status": "COMPLETED",
            "action": action,
            "idempotency_key": "business-action",
        }

    monkeypatch.setattr(automation, "_invoke_action", invoke)
    return store, calls


def test_new_execution_reuses_actions_and_records_both_attempts(prepared):
    store, calls = prepared
    first = automation.execute_automation(store, event(), "tenant-a")
    retry = automation.execute_automation(store, event("exec-2"), "tenant-a")
    assert first["executed_actions"] == retry["executed_actions"]
    assert len(calls) == 1
    with store.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) AS n FROM automation_executions").fetchone()[
                "n"
            ]
            == 1
        )
        assert (
            db.execute(
                "SELECT COUNT(*) AS n FROM automation_execution_attempts"
            ).fetchone()["n"]
            == 2
        )
    receipts = [
        automation.record_execution_result(store, result(attempt), "tenant-a")
        for attempt in ("exec-1", "exec-2")
    ]
    assert receipts[0].event_id != receipts[1].event_id
    assert automation.record_execution_result(
        store, result("exec-2"), "tenant-a"
    ).duplicate
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("payload", {"changed": True}),
        ("tenant_id", "tenant-b"),
        ("event_id", "other"),
        ("automation_key", "other"),
    ],
)
def test_attempt_cannot_be_rebound(prepared, field, new_value):
    store, calls = prepared
    automation.execute_automation(store, event(), "tenant-a")
    changed = event()
    changed[field] = new_value
    with pytest.raises(ControlPlaneError, match="idempotency_conflict"):
        automation.execute_automation(store, changed, changed["tenant_id"])
    assert len(calls) == 1


def test_new_attempt_changed_business_content_is_conflict(prepared):
    store, calls = prepared
    automation.execute_automation(store, event(), "tenant-a")
    changed = event("exec-2")
    changed["payload"] = {"changed": True}
    with pytest.raises(ControlPlaneError, match="idempotency_conflict"):
        automation.execute_automation(store, changed, "tenant-a")
    with store.connect() as db:
        assert (
            db.execute(
                "SELECT 1 FROM automation_execution_attempts WHERE execution_id='exec-2'"
            ).fetchone()
            is None
        )


def test_late_failure_cannot_downgrade_success(prepared):
    store, calls = prepared
    for attempt in ("exec-1", "exec-2"):
        automation.execute_automation(store, event(attempt), "tenant-a")
    automation.record_execution_result(store, result("exec-2"), "tenant-a")
    failure = result("exec-1", "FAILED")
    failure.update(event_id="resolve", workflow_key="resolve", correlation_id="resolve")
    automation.record_execution_result(store, failure, "tenant-a")
    automation.execute_automation(store, event("exec-3"), "tenant-a")
    with store.connect() as db:
        assert (
            db.execute("SELECT status FROM automation_executions").fetchone()["status"]
            == "COMPLETED"
        )
        rows = {
            row["execution_id"]: row["status"]
            for row in db.execute(
                "SELECT execution_id,status FROM automation_execution_attempts"
            )
        }
    assert rows["exec-1"] == "FAILED" and rows["exec-2"] == "COMPLETED"
    assert len(calls) == 1


def test_failure_then_successful_retry_uses_existing_receipt(prepared):
    store, calls = prepared
    automation.execute_automation(store, event(), "tenant-a")
    automation.record_execution_result(store, result(status="FAILED"), "tenant-a")
    automation.execute_automation(store, event("exec-2"), "tenant-a")
    automation.record_execution_result(store, result("exec-2"), "tenant-a")
    assert len(calls) == 1


def test_cross_tenant_and_wrong_result_identity_leave_no_event(prepared):
    store, _ = prepared
    automation.execute_automation(store, event(), "tenant-a")
    with pytest.raises(ControlPlaneError, match="cross_tenant_denied"):
        automation.record_execution_result(store, result(), "tenant-b")
    bad = result()
    bad["workflow_key"] = "forged"
    with pytest.raises(ControlPlaneError, match="automation_execution_not_found"):
        automation.record_execution_result(store, bad, "tenant-a")
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] == 0


def test_action_body_stays_byte_identical_across_attempts(tmp_path, monkeypatch):
    secret = tmp_path / "secret"
    secret.write_bytes(b"isolated-action-test-material-long-enough")
    monkeypatch.setenv("CONTROL_PLANE_AUTOMATION_ACTION_SECRET_FILE", str(secret))
    monkeypatch.setenv(
        "CONTROL_PLANE_ACTION_CRM_CUSTOMER_SYNCHRONIZE_URL", "http://localhost/action"
    )
    bodies = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            body = json.loads(bodies[-1])
            return json.dumps(
                {
                    "status": "COMPLETED",
                    "action": body["action"],
                    "idempotency_key": body["idempotency_key"],
                }
            ).encode()

    def send(request, timeout):
        bodies.append(request.data)
        return Response()

    monkeypatch.setattr(automation.urllib.request, "urlopen", send)
    for attempt in ("exec-1", "exec-2"):
        value = event(attempt)
        value.update(authorized=True, policy_checked_at=attempt)
        automation._invoke_action("crm.customer.synchronize", value, "a" * 64)
    assert bodies[0] == bodies[1]
    assert "orchestration_execution_id" not in json.loads(bodies[0])["event"]


def test_first_attempt_mapping_is_backfilled_for_legacy_operations(prepared):
    store, _ = prepared
    automation.execute_automation(store, event(), "tenant-a")
    with store.connect() as db:
        db.execute("DELETE FROM automation_execution_attempts")
    automation.execute_automation(store, event("exec-2"), "tenant-a")
    automation.record_execution_result(store, result(), "tenant-a")


@pytest.mark.parametrize('field,bad_value', [
    ('status', []), ('status', {}), ('execution_id', 123), ('execution_id', ''),
    ('event_id', None), ('correlation_id', 'x\ny'), ('idempotency_key', 'x' * 2049),
    ('actions', [None]), ('actions', [{'type': []}]),
    ('actions', [{'type': 'x'}, {'type': 'x'}]), ('actions', 'not-a-list'),
    ('completed_at', 'yesterday'), ('completed_at', '2026-09-07T00:00:01'),
])
def test_invalid_result_rejected_without_state_change(prepared, field, bad_value):
    store, calls = prepared
    automation.execute_automation(store, event(), 'tenant-a')
    with store.connect() as db:
        before = dict(db.execute('SELECT * FROM automation_executions').fetchone())
        count = db.execute('SELECT count(*) AS n FROM events').fetchone()['n']
    malformed = result()
    malformed[field] = bad_value
    with pytest.raises(ControlPlaneError):
        automation.record_execution_result(store, malformed, 'tenant-a')
    with store.connect() as db:
        assert dict(db.execute('SELECT * FROM automation_executions').fetchone()) == before
        assert db.execute('SELECT count(*) AS n FROM events').fetchone()['n'] == count
    assert len(calls) == 1
