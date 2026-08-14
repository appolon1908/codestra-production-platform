import concurrent.futures

import pytest

from control_plane.reservation import ReservationConflict, ReservationStore


def test_idempotent_reservation_and_outbox_are_atomic(tmp_path) -> None:
    store = ReservationStore(tmp_path / "state.sqlite3")
    request = dict(
        idempotency_key="idem-1",
        reservation_id="reservation-1",
        tenant_id="tenant-a",
        campaign_id="COD-WEB-OUT",
        lead_id="lead-1",
        owner_id="agent-1",
    )
    assert store.reserve(**request) == store.reserve(**request)
    assert store.reconcile() == {
        "status": "healthy",
        "active_reservations": 1,
        "pending": 1,
        "delivered": 0,
        "missing_outbox": 0,
    }
    store.mark_delivered("lead.reserved:reservation-1")
    assert store.reconcile()["delivered"] == 1


def test_concurrent_reservation_has_one_winner(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    ReservationStore(path)

    def reserve(number: int) -> str:
        try:
            ReservationStore(path).reserve(
                idempotency_key=f"idem-{number}",
                reservation_id=f"reservation-{number}",
                tenant_id="tenant-a",
                campaign_id="COD-WEB-OUT",
                lead_id="lead-1",
                owner_id=f"agent-{number}",
            )
            return "won"
        except ReservationConflict:
            return "blocked"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert results.count("won") == 1
    assert results.count("blocked") == 7


def test_idempotency_conflict_is_rejected(tmp_path) -> None:
    store = ReservationStore(tmp_path / "state.sqlite3")
    common = dict(
        idempotency_key="same-key",
        reservation_id="reservation-1",
        tenant_id="tenant-a",
        campaign_id="COD-WEB-OUT",
        lead_id="lead-1",
    )
    store.reserve(**common, owner_id="agent-1")
    with pytest.raises(ReservationConflict, match="different request"):
        store.reserve(**common, owner_id="agent-2")
