import copy
import json
import stat
from pathlib import Path

import pytest

from control_plane_service import calling_evidence as producer
from control_plane_service import calling_readiness as readiness
from test_calling_readiness import NOW, codes, evidence


def test_producer_and_evaluator_use_the_same_required_runtime_flags():
    expected, observed = evidence()
    for flag in readiness.FLAGS:
        observed["safety"][flag] = "DISABLED"
    before = copy.deepcopy(observed)
    result = producer.build_observed(observed)
    assert readiness.evaluate(expected, result, now=NOW)["status"] == "READBACK_MATCHES"
    assert all(result["safety"][flag] is False for flag in readiness.FLAGS)
    assert result["captured_at"] == before["captured_at"]
    assert result["server_b"] == before["server_b"]
    assert observed == before


@pytest.mark.parametrize("flag", ["ENABLE_AGENT_PROVISIONING", "ENABLE_INTERNAL_TEST_CALLING"])
def test_new_flags_require_explicit_readback_and_cannot_default_off(flag):
    expected, observed = evidence()
    del observed["safety"][flag]
    with pytest.raises(ValueError, match="incomplete runtime safety observations"):
        producer.build_observed(observed)
    for value in (None, "enabled", True):
        observed["safety"][flag] = value
        result = producer.build_observed(observed)
        assert "EFFECT_NOT_DISABLED:" + flag in codes(readiness.evaluate(expected, result, now=NOW))


@pytest.mark.parametrize("value", [0, 1, [], {}, "unknown", ""])
def test_malformed_runtime_flags_are_not_coerced_to_false(value):
    _, observed = evidence()
    observed["safety"]["ENABLE_INTERNAL_TEST_CALLING"] = value
    with pytest.raises(ValueError, match="invalid runtime safety observation"):
        producer.build_observed(observed)


def test_publish_is_atomic_and_does_not_refresh_observations(tmp_path):
    expected, observed = evidence()
    source, target = tmp_path / "readback.json", tmp_path / "observed.json"
    source.write_text(json.dumps(observed))
    target.write_text("old evidence")
    producer.publish(source, target)
    result = readiness._read(target)
    assert result == observed
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert readiness.evaluate(expected, result, now=NOW)["status"] == "READBACK_MATCHES"
    assert not list(tmp_path.glob(".calling-observed-*"))


def test_rejected_input_preserves_previously_published_evidence(tmp_path):
    source, target = tmp_path / "readback.json", tmp_path / "observed.json"
    source.write_text('{"safety": {}, "safety": {}}')
    target.write_text("previous evidence")
    with pytest.raises(ValueError):
        producer.publish(source, target)
    assert target.read_text() == "previous evidence"


def test_published_contract_lists_every_required_flag():
    doc = (Path(__file__).parents[1] / "docs/CALLING_READINESS_API.md").read_text()
    assert all("`" + flag + "`" in doc for flag in readiness.FLAGS)
