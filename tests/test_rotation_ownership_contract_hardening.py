"""Regression tests for exact runtime-secret store and consumer ownership."""

import copy
import json

import pytest

from tools.validate_runtime_rotation_ownership import ROOT, validate, validate_environment


def runtime_contract():
    return json.loads((ROOT / "config/runtime-secret-rotation-ownership.json").read_text())


def environment_contract():
    return json.loads((ROOT / "config/environment-secret-rotation-ownership.json").read_text())


def klyrow_runtime(document):
    return next(item for item in document["entries"] if item["secret_id"] == "KLYROW_WEBHOOK_SECRET")


def test_checked_in_ownership_contracts_are_valid():
    validate(runtime_contract())
    validate_environment(environment_contract())


@pytest.mark.parametrize(("consumer", "environment"), [
    ("private-integration-gateway", "/etc/kyqra-telnexa-integration/shared.env"),
    ("codestra-email-reseller-api-1", "/etc/codestra/secrets/kyqra-telnexa/middleware.env"),
])
def test_each_separate_klyrow_verifier_has_complete_proof(consumer, environment):
    entry = klyrow_runtime(runtime_contract())
    record = next(item for item in entry["consumers"] if item["name"] == consumer)
    assert record["runtime_environment"] == environment
    for field in ("restart_boundary", "new_secret_acceptance", "old_secret_rejection", "rollback", "evidence"):
        assert record[field]


@pytest.mark.parametrize("path", [
    "/etc/codestra/secrets/control-plane.env",
    "/etc/kyqra-telnexa-integration/shared.env",
    "/etc/codestra/secrets/kyqra-telnexa/middleware.env",
])
def test_missing_klyrow_runtime_store_fails_closed(path):
    document = runtime_contract()
    entry = klyrow_runtime(document)
    entry["runtime_stores"] = [item for item in entry["runtime_stores"] if item["path"] != path]
    with pytest.raises(ValueError, match="runtime store inventory incomplete"):
        validate(document)


def test_private_gateway_cannot_be_assigned_to_control_plane_store():
    document = runtime_contract()
    entry = klyrow_runtime(document)
    store = next(item for item in entry["runtime_stores"] if item["path"] == "/etc/codestra/secrets/control-plane.env")
    store["restart_boundary"].append("private-integration-gateway-1")
    with pytest.raises(ValueError, match="restart boundary is not exact"):
        validate(document)


@pytest.mark.parametrize("consumer", ["private-integration-gateway-1", "codestra-email-reseller-api-1"])
def test_environment_contract_requires_each_klyrow_verifier(consumer):
    document = environment_contract()
    entry = next(item for item in document["secrets"] if item["secret_id"] == "KLYROW_WEBHOOK_SECRET")
    entry["consumers"].remove(consumer)
    with pytest.raises(ValueError, match="environment consumer inventory incomplete"):
        validate_environment(document)


def test_duplicate_environment_store_fails_closed():
    document = environment_contract()
    document["environment_files"].append(copy.deepcopy(document["environment_files"][0]))
    with pytest.raises(ValueError, match="environment file inventory incomplete"):
        validate_environment(document)


def test_environment_restart_boundary_must_match_runtime_contract():
    document = environment_contract()
    store = next(item for item in document["environment_files"] if item["path"] == "/etc/kyqra-telnexa-integration/shared.env")
    store["restart_boundary"] = ["codestra-email-reseller-api-1"]
    with pytest.raises(ValueError, match="restart boundary mismatch"):
        validate_environment(document)


def test_contracts_do_not_claim_live_rotation_or_activation():
    for entry in runtime_contract()["entries"]:
        assert entry["live_inventory_status"] == "PENDING"
        assert entry["activation_allowed"] is False
