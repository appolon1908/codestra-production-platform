import sys
import types

import pytest

try:
    import pymysql  # noqa: F401
except ModuleNotFoundError:
    pymysql = types.ModuleType("pymysql")
    pymysql.cursors = types.SimpleNamespace(DictCursor=object)
    pymysql.connect = lambda **_: None
    sys.modules["pymysql"] = pymysql

from tel_events import service
from tel_events.publisher import Cursor, PublisherError, SourceBoundary, build_call_ended_event


class FakeCursor:
    def __init__(self):
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []


class FakeDB:
    def __init__(self):
        self.value = FakeCursor()

    def cursor(self):
        return self.value


def test_rows_preserve_hard_boundary_and_composite_cursor():
    db = FakeDB()
    assert service._rows(db, "vicidial_log", 1000, 2000, "1.2", 10) == []
    assert "end_epoch > %s" in db.value.sql
    assert "(end_epoch > %s OR (end_epoch = %s AND uniqueid > %s))" in db.value.sql
    assert db.value.params == (1000, 2000, 2000, "1.2", 10)


@pytest.mark.parametrize("limit", [0, 101])
def test_rows_reject_unbounded_batches(limit):
    with pytest.raises(PublisherError, match="batch limit"):
        service._rows(FakeDB(), "vicidial_log", 1000, 2000, "1.2", limit)


def test_canary_policy_requires_bounded_scope(monkeypatch):
    monkeypatch.setenv("TEL_EVENTS_MODE", "canary")
    monkeypatch.setenv("TEL_EVENTS_EVENT_BUDGET", "10")
    monkeypatch.setenv("TEL_EVENTS_CAMPAIGN_ALLOWLIST", "C1,C2")
    monkeypatch.setenv("TEL_EVENTS_USER_GROUP_ALLOWLIST", "TL")
    policy = service._runtime_policy()
    assert policy.event_budget == 10
    assert policy.campaigns == frozenset(("C1", "C2"))
    assert policy.user_groups == frozenset(("TL",))

    monkeypatch.setenv("TEL_EVENTS_EVENT_BUDGET", "11")
    with pytest.raises(PublisherError, match="between 5 and 10"):
        service._runtime_policy()


def test_policy_rejects_missing_allowlist(monkeypatch):
    monkeypatch.setenv("TEL_EVENTS_MODE", "canary")
    monkeypatch.setenv("TEL_EVENTS_EVENT_BUDGET", "5")
    monkeypatch.setenv("TEL_EVENTS_CAMPAIGN_ALLOWLIST", "")
    monkeypatch.setenv("TEL_EVENTS_USER_GROUP_ALLOWLIST", "TL")
    with pytest.raises(PublisherError, match="CAMPAIGN_ALLOWLIST"):
        service._runtime_policy()


def test_event_outside_approved_scope_is_not_deliverable():
    policy = service.RuntimePolicy(
        mode="canary",
        event_budget=5,
        campaigns=frozenset(("C1",)),
        user_groups=frozenset(("TL",)),
    )
    event = build_call_ended_event(
        {
            "uniqueid": "1.2",
            "end_epoch": 2000,
            "length_in_sec": 30,
            "status": "SALE",
            "campaign_id": "UNAPPROVED",
            "user_group": "TL",
        },
        "vicidial_log",
    )
    assert service._in_scope(event, policy) is False


def test_round_robin_prevents_source_starvation():
    a = SourceBoundary("vicidial_log", 0, Cursor(0, "0"))
    b = SourceBoundary("vicidial_closer_log", 0, Cursor(0, "0"))
    rows = list(service._round_robin([(a, [{"id": "a1"}, {"id": "a2"}]), (b, [{"id": "b1"}, {"id": "b2"}])]))
    assert [(boundary.table, row["id"]) for boundary, row in rows] == [
        ("vicidial_log", "a1"), ("vicidial_closer_log", "b1"),
        ("vicidial_log", "a2"), ("vicidial_closer_log", "b2"),
    ]


def test_signature_binds_method_path_event_and_exact_body():
    baseline = service._signature_input("POST", "/v1/events/", "10", "event-1", b"{}")
    changed = (
        service._signature_input("PUT", "/v1/events/", "10", "event-1", b"{}"),
        service._signature_input("POST", "/v1/other", "10", "event-1", b"{}"),
        service._signature_input("POST", "/v1/events", "11", "event-1", b"{}"),
        service._signature_input("POST", "/v1/events", "10", "event-2", b"{}"),
        service._signature_input("POST", "/v1/events", "10", "event-1", b"{ }")
    )
    assert all(candidate != baseline for candidate in changed)


def test_cli_success_does_not_use_sent_count_as_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(service, "run_once", lambda: 3)
    assert service.main([]) == 0
    assert capsys.readouterr().out.strip() == "TEL_EVENTS_SENT=3"
