import csv
from pathlib import Path

import pytest

from scripts.full_campaign_reconciliation import (
    ReconciliationError,
    load_desired,
    reconcile,
)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def desired(tmp_path: Path, *, active: str = "false") -> Path:
    return write_csv(
        tmp_path / "odoo.csv",
        ["canonical_campaign_code", "vicidial_campaign_id", "environment", "active"],
        [{
            "canonical_campaign_code": "COD-WEB-OUT",
            "vicidial_campaign_id": "COD20821",
            "environment": "production",
            "active": active,
        }],
    )


def test_complete_disabled_mapping_passes(tmp_path: Path) -> None:
    mw = write_csv(
        tmp_path / "mw.csv",
        ["canonical_campaign_code", "vicidial_campaign_id"],
        [{"canonical_campaign_code": "COD-WEB-OUT", "vicidial_campaign_id": "COD20821"}],
    )
    vd = write_csv(
        tmp_path / "vd.csv",
        ["campaign_id", "campaign_description", "active", "auto_dial_level"],
        [{"campaign_id": "COD20821", "campaign_description": "CODESTRA:COD-WEB-OUT", "active": "N", "auto_dial_level": "0"}],
    )
    rows, legacy = reconcile(load_desired(desired(tmp_path)), mw, vd)
    assert rows[0]["status"] == "PASS"
    assert rows[0]["reasons"] == []
    assert legacy == []


def test_missing_mapping_and_campaign_fail_closed(tmp_path: Path) -> None:
    mw = write_csv(tmp_path / "mw.csv", ["canonical_campaign_code", "vicidial_campaign_id"], [])
    vd = write_csv(tmp_path / "vd.csv", ["campaign_id", "campaign_description", "active", "auto_dial_level"], [])
    rows, _ = reconcile(load_desired(desired(tmp_path)), mw, vd)
    assert rows[0]["status"] == "BLOCKED"
    assert rows[0]["reasons"] == ["MIDDLEWARE_MAPPING_MISSING", "VICIDIAL_CAMPAIGN_MISSING"]


def test_active_production_desired_state_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ReconciliationError, match="active production"):
        load_desired(desired(tmp_path, active="true"))


def test_unowned_or_active_vicidial_collision_is_blocked(tmp_path: Path) -> None:
    mw = write_csv(
        tmp_path / "mw.csv",
        ["canonical_campaign_code", "vicidial_campaign_id"],
        [{"canonical_campaign_code": "COD-WEB-OUT", "vicidial_campaign_id": "COD20821"}],
    )
    vd = write_csv(
        tmp_path / "vd.csv",
        ["campaign_id", "campaign_description", "active", "auto_dial_level"],
        [{"campaign_id": "COD20821", "campaign_description": "legacy", "active": "Y", "auto_dial_level": "1"}],
    )
    rows, _ = reconcile(load_desired(desired(tmp_path)), mw, vd)
    assert rows[0]["status"] == "BLOCKED"
    assert set(rows[0]["reasons"]) == {
        "VICIDIAL_OWNERSHIP_MARKER_MISMATCH",
        "VICIDIAL_CAMPAIGN_NOT_DISABLED",
        "VICIDIAL_AUTO_DIAL_NOT_ZERO",
    }


def test_unmanaged_legacy_campaign_is_reported_not_mutated(tmp_path: Path) -> None:
    mw = write_csv(tmp_path / "mw.csv", ["canonical_campaign_code", "vicidial_campaign_id"], [])
    vd = write_csv(
        tmp_path / "vd.csv",
        ["campaign_id", "campaign_description", "active", "auto_dial_level"],
        [{"campaign_id": "CODESTRA", "campaign_description": "legacy", "active": "Y", "auto_dial_level": "1"}],
    )
    _, legacy = reconcile(load_desired(desired(tmp_path)), mw, vd)
    assert [row["campaign_id"] for row in legacy] == ["CODESTRA"]


def test_malformed_observed_csv_is_rejected(tmp_path: Path) -> None:
    mw = write_csv(tmp_path / "mw.csv", ["canonical_campaign_code", "vicidial_campaign_id"], [])
    vd = tmp_path / "vd.csv"
    vd.write_text("campaign_id,campaign_description,active,auto_dial_level\nCOD20821,bad,field,N,0\n")
    with pytest.raises(ReconciliationError, match="malformed observed CSV"):
        reconcile(load_desired(desired(tmp_path)), mw, vd)
