"""Regression coverage for the combined PR #275 / protected-base quarantine."""

import argparse
import json

import pytest

from tools import validate_activation_request as activation
from tools import validate_quarantined_recovery as recovery


def matching_request(tmp_path, sha, action):
    digest = "sha256:" + "a" * 64
    manifest = tmp_path / "deployment-manifest.json"
    manifest.write_text(json.dumps({
        "commit": sha,
        "release_tuple": {"middleware_image_digest": digest},
        "required_flags": {name: False for name in activation.REQUIRED_FALSE_FLAGS},
    }))
    return argparse.Namespace(
        action=action, sha=sha, digest=digest, change_id=activation.CHANGE_ID,
        maintenance_date="2099-08-21", manifest=str(manifest),
    )


def registry(tmp_path, monkeypatch, releases):
    path = tmp_path / "revocations.json"
    path.write_text(json.dumps({"schema_version": 1, "releases": releases}))
    monkeypatch.setattr(activation, "NON_ACTIVATABLE_RELEASES", path)


@pytest.mark.parametrize("action", sorted(activation.ACTIONS))
def test_permanent_quarantine_survives_empty_registry(tmp_path, monkeypatch, action):
    registry(tmp_path, monkeypatch, [])
    sha = "01f2676772b11919e1d79cc74d36bc5eeaa682cd"
    with pytest.raises(ValueError, match="explicitly non-activatable"):
        activation.validate(matching_request(tmp_path, sha, action))


@pytest.mark.parametrize("action", sorted(activation.ACTIONS))
def test_protected_registry_denies_additional_release(tmp_path, monkeypatch, action):
    sha = "2" * 40
    assert sha not in activation.NON_ACTIVATABLE_SHAS
    registry(tmp_path, monkeypatch, [{"protected_sha": sha}])
    with pytest.raises(ValueError, match="explicitly non-activatable"):
        activation.validate(matching_request(tmp_path, sha, action))


@pytest.mark.parametrize("contents", [None, "{invalid-json"])
def test_missing_or_invalid_registry_fails_closed(tmp_path, monkeypatch, contents):
    path = tmp_path / "revocations.json"
    if contents is not None:
        path.write_text(contents)
    monkeypatch.setattr(activation, "NON_ACTIVATABLE_RELEASES", path)
    with pytest.raises((OSError, ValueError)):
        activation.validate(matching_request(tmp_path, "3" * 40, "preflight"))


@pytest.mark.parametrize("action", sorted(recovery.RECOVERY_ACTIONS))
def test_quarantine_actions_use_separate_fixed_recovery_path(tmp_path, action):
    assert recovery.RECOVERY_ACTIONS == activation.RECOVERY_ONLY_ACTIONS
    values = recovery.validated_tuple(action)
    assert values["action"] == action
    assert values["protected_sha"] in activation.NON_ACTIVATABLE_SHAS
    with pytest.raises(ValueError, match="explicitly non-activatable"):
        activation.validate(matching_request(tmp_path, values["protected_sha"], action))


@pytest.mark.parametrize("action", sorted(activation.ACTIONS - recovery.RECOVERY_ACTIONS))
def test_other_activation_actions_cannot_enter_recovery_dispatch(action):
    with pytest.raises(ValueError, match="recovery-only"):
        recovery.validated_tuple(action)
