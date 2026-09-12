from datetime import datetime, timezone

import pytest

from control_plane.portfolio_status import portfolio_status


ALL_GATES = {name: True for name in ("source_locked", "image_pinned", "checks_green", "approval_recorded")}


def test_portfolio_status_fails_closed_without_all_gates() -> None:
    result = portfolio_status({"source_locked": True})
    assert result["status"] == "blocked"
    assert result["external_effects"] == "disabled"
    assert set(result["failed_gates"]) == {"image_pinned", "checks_green", "approval_recorded"}
    assert result["gate_count"] == 4


def test_portfolio_status_ready_payload_is_secret_free() -> None:
    result = portfolio_status(ALL_GATES, as_of=datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert result["status"] == "ready"
    assert result["failed_gates"] == []
    assert result["as_of"] == "2026-09-11T00:00:00+00:00"
    assert all("secret" not in key.lower() for key in result)


def test_unknown_gate_names_are_ignored_for_forward_compatibility() -> None:
    result = portfolio_status({**ALL_GATES, "future_gate": True})
    assert result["status"] == "ready"
    assert set(result["gates"]) == {"source_locked", "image_pinned", "checks_green", "approval_recorded"}


def test_non_boolean_gate_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="booleans"):
        portfolio_status({"checks_green": "true"})  # type: ignore[arg-type]


def test_naive_timestamps_are_explicitly_utc() -> None:
    result = portfolio_status(ALL_GATES, as_of=datetime(2026, 9, 11))
    assert result["as_of"] == "2026-09-11T00:00:00+00:00"
