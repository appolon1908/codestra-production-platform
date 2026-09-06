from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "orbit_validator", ROOT / "tools" / "validate_orbit_adoption.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def documents():
    return (
        validator.load_json(validator.MANIFEST_PATH),
        validator.load_json(validator.SCHEMA_PATH),
        validator.load_json(validator.LEDGER_PATH),
        validator.load_json(validator.GATES_PATH),
    )


def current_paths():
    return [
        "orbit/README.md",
        "orbit/adoption-manifest.json",
        "orbit/adoption-ledger.json",
        "orbit/runtime-activation-gates.json",
        "orbit/contracts/adoption-manifest.schema.json",
        "tools/validate_orbit_adoption.py",
        "tests/test_orbit_adoption.py",
        ".github/workflows/orbit-adoption.yml",
    ]


def test_current_contract_is_valid_and_fail_closed():
    manifest, schema, ledger, gates = documents()
    validator.validate_contract(manifest, schema, ledger, gates, current_paths())
    assert manifest["productionReady"] is False
    assert manifest["runtimeActivated"] is False
    assert gates["overallStatus"] == "BLOCKED"


def test_schema_rejects_feature_branch_as_target():
    manifest, schema, _ledger, _gates = documents()
    manifest["targetBranch"] = "codex/codestra-orbit-v2-codestra-production-platform"
    with pytest.raises(validator.ContractError, match="schema validation"):
        validator.validate_schema(manifest, schema)


def test_pending_candidate_cannot_be_installable():
    manifest, schema, ledger, gates = documents()
    manifest["packages"][0]["installAllowed"] = True
    manifest["packages"][0]["sha256"] = "a" * 64
    with pytest.raises(validator.ContractError, match="non-installable"):
        validator.validate_contract(manifest, schema, ledger, gates, current_paths())


def test_competing_ui_or_package_sources_are_rejected():
    manifest, schema, ledger, gates = documents()
    paths = current_paths() + ["orbit/packages/ui/src/index.js"]
    with pytest.raises(validator.ContractError, match="competing UI/package"):
        validator.validate_contract(manifest, schema, ledger, gates, paths)


def test_certified_state_requires_complete_evidence():
    manifest, schema, ledger, gates = documents()
    manifest["status"] = "PRODUCTION_CERTIFIED"
    manifest["productionReady"] = True
    manifest["runtimeActivated"] = True
    manifest["blockers"] = []
    with pytest.raises(validator.ContractError, match="protected SDK source SHA"):
        validator.validate_contract(manifest, schema, ledger, gates, current_paths())


def test_runtime_gate_inventory_is_exact_and_ordered():
    manifest, schema, ledger, gates = documents()
    gates["gates"] = list(reversed(gates["gates"]))
    with pytest.raises(validator.ContractError, match="inventory or order"):
        validator.validate_contract(manifest, schema, ledger, gates, current_paths())
