import json
from pathlib import Path

from tools.verify_kong_source_lock import load_lock, verify_local_absence

ROOT = Path(__file__).resolve().parents[1]


def test_kong_source_lock_is_exact_and_fail_closed():
    lock = load_lock()
    assert lock["repository"] == "appolon1908-hue/Kong"
    assert lock["commit"] == "007055bbd05b9cd1c7cc33d3810ec17a3ec9fbba"
    assert lock["production_state_changed"] is False
    verify_local_absence(lock)


def test_platform_keeps_only_cross_system_route_summary():
    lock = json.loads((ROOT / "config/kong-source.lock.json").read_text())
    assert len(lock["public_routes"]) == 7
    assert all(
        row["hosts"] == ["api.codestra.co"]
        for row in lock["public_routes"]
    )
    assert not any(
        (ROOT / relative).exists()
        for relative in lock["local_implementation_paths_must_be_absent"]
    )
