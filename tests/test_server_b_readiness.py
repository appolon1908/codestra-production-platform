"""Server B runtime regressions must reach the existing readiness API gate."""
import copy
import json
from datetime import timedelta

import pytest

from control_plane_service import calling_readiness as readiness
from control_plane_service import server_b_readiness as server_b
from test_calling_readiness import NOW, codes, evidence


def result_for(update):
    expected, observed = evidence()
    update(observed["server_b"])
    return readiness.evaluate(expected, observed, now=NOW)


@pytest.mark.parametrize("field,value,code", [
    ("public_ip", "65.109.65.169", "PUBLIC_IP_MISMATCH"),
    ("private_ip", "10.40.0.1", "PRIVATE_IP_MISMATCH"),
    ("source_sha", "c" * 40, "SOURCE_SHA_MISMATCH"),
    ("artifact_digest", "sha256:" + "c" * 64, "ARTIFACT_DIGEST_MISMATCH"),
    ("release_digest", "sha256:" + "d" * 64, "RELEASE_DIGEST_MISMATCH"),
    ("deployment_profile", "production-external-one-call", "READONLY_PROFILE_NOT_PROVEN"),
    ("config_drift_count", 4, "CONFIG_DRIFT_COUNT_NONZERO_OR_UNKNOWN"),
    ("outbox_depth", 87, "OUTBOX_DEPTH_NONZERO_OR_UNKNOWN"),
    ("quarantined_events", 51, "QUARANTINED_EVENTS_NONZERO_OR_UNKNOWN"),
])
def test_runtime_blockers_override_healthy_component_assertions(field, value, code):
    result = result_for(lambda doc: doc.update({field: value}))
    assert result["status"] == "BLOCKED"
    assert {"component": "vicidial", "code": "SERVER_B_" + code} in result["blockers"]


@pytest.mark.parametrize("field", server_b.REQUIRED_CHECKS)
@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_runtime_checks_are_explicit_booleans(field, value):
    result = result_for(lambda doc: doc.update({field: value}))
    assert "SERVER_B_" + field.upper() + "_NOT_PROVEN" in codes(result)


@pytest.mark.parametrize("field", server_b.ZERO_COUNTERS)
@pytest.mark.parametrize("value", [1, -1, False, "0", None])
def test_missing_or_invalid_zero_counters_are_not_health(field, value):
    assert result_for(lambda doc: doc.update({field: value}))["status"] == "BLOCKED"


@pytest.mark.parametrize("age", [-1, 301])
def test_refreshing_outer_evidence_cannot_refresh_server_b(age):
    result = result_for(lambda doc: doc.update(
        captured_at=(NOW - timedelta(seconds=age)).isoformat()))
    assert "SERVER_B_STALE_OR_INVALID_EVIDENCE" in codes(result)


@pytest.mark.parametrize("value", [None, 123, {}, [], "invalid", "2026-09-09T12:00:00"])
def test_malformed_server_timestamp_fails_closed(value):
    assert result_for(lambda doc: doc.update(captured_at=value))["status"] == "BLOCKED"


@pytest.mark.parametrize("unit", server_b.HEALTH_UNITS)
@pytest.mark.parametrize("change", [
    {"result": "exit-code", "exit_status": 1}, {"result": None},
    {"last_success_age_seconds": None}, {"last_success_age_seconds": 301},
    {"last_success_age_seconds": -1}, {"exit_status": False},
])
def test_each_health_unit_requires_recent_successful_execution(unit, change):
    result = result_for(lambda doc: doc["health_units"][unit].update(change))
    assert "SERVER_B_HEALTH_UNIT_NOT_PROVEN:" + unit in codes(result)


def test_absent_or_reset_probe_is_not_treated_as_success():
    result = result_for(lambda doc: doc.update(health_units={}))
    assert sum("HEALTH_UNIT_NOT_PROVEN" in code for code in codes(result)) == 3


def test_zero_process_counts_do_not_establish_zero_durable_calls():
    result = result_for(lambda doc: doc["call_counters"].update(
        authority="asterisk-process-lifetime", calls_placed_after=1))
    assert "SERVER_B_CALL_COUNTER_AUTHORITY_NOT_PROVEN" in codes(result)
    assert "SERVER_B_CALLS_PLACED_AFTER_NONZERO_OR_UNKNOWN" in codes(result)


@pytest.mark.parametrize("field", ["calls_placed_before", "calls_placed_after"])
@pytest.mark.parametrize("value", [1, False, "0", None])
def test_durable_call_counters_cannot_be_missing_or_coerced(field, value):
    result = result_for(lambda doc: doc["call_counters"].update({field: value}))
    assert "SERVER_B_" + field.upper() + "_NONZERO_OR_UNKNOWN" in codes(result)


@pytest.mark.parametrize("section", ["server_b", "health_units", "call_counters"])
def test_malformed_nested_evidence_is_bounded_and_redacted(section):
    expected, observed = evidence()
    if section == "server_b":
        observed[section] = ["private-value"]
    else:
        observed["server_b"][section] = ["private-value"]
    before = copy.deepcopy(observed)
    result = readiness.evaluate(expected, observed, now=NOW)
    assert result["status"] == "BLOCKED"
    assert "private-value" not in json.dumps(result)
    assert observed == before
