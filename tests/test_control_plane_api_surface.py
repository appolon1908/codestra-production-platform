from __future__ import annotations

import subprocess
from pathlib import Path

from tools.check_control_plane_api_surface import (
    REQUIRED_FIELDS,
    coverage_gaps,
    load_yaml,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/control-plane-api-surface.yaml"
OPTIONAL_FIELDS = {"remediation", "idempotency_exemption"}


def manifest():
    return load_yaml(MANIFEST_PATH)


def test_control_plane_api_inventory_matches_current_sources() -> None:
    assert validate(ROOT, manifest()) == []


def test_endpoint_rows_contain_only_governed_fields() -> None:
    unexpected = {
        row["endpoint_id"]: sorted(set(row) - REQUIRED_FIELDS - OPTIONAL_FIELDS)
        for row in manifest()["endpoints"]
        if set(row) - REQUIRED_FIELDS - OPTIONAL_FIELDS
    }
    assert unexpected == {}


def test_missing_contract_layers_are_explicit_and_owned() -> None:
    gaps = coverage_gaps(manifest())
    assert gaps
    identities = {finding.location for finding in gaps}
    assert "postal-inbound" in identities
    assert "crm-account" in identities
    assert "mapping-job-read" in identities
    assert all(finding.message for finding in gaps)


def test_strict_predeployment_api_coverage_gate_fails_closed() -> None:
    result = subprocess.run(
        ["python", "tools/check_control_plane_api_surface.py", "--strict"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "CONTROL_PLANE_API_SURFACE=FAIL" in result.stdout
    assert "COVERAGE_GAPS=" in result.stdout


def test_public_business_apis_are_never_marked_kong_not_required() -> None:
    unsafe = [
        row["endpoint_id"]
        for row in manifest()["endpoints"]
        if row["exposure"] == "public_api" and row["kong"] == "not_required"
    ]
    assert unsafe == []


def test_mutating_apis_declare_idempotency() -> None:
    mutating = {"POST", "PUT", "PATCH", "DELETE"}
    missing = [
        row["endpoint_id"]
        for row in manifest()["endpoints"]
        if mutating.intersection(row["methods"])
        and row["idempotency"] not in {"required", "exempt"}
    ]
    assert missing == []
