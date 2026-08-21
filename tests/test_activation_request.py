import argparse
import json

import pytest

from tools.validate_activation_request import CHANGE_ID, REQUIRED_FALSE_FLAGS, validate

SHA = "24c49e08e53d5e3b9894b0b6f959a942533ed276"
DIGEST = "sha256:336c9a31648a0481737fa4bcc3eafb02a22e4b4fc66ba7b8ec1759c087e05e02"


def request(tmp_path, **changes):
    manifest = tmp_path / "deployment-manifest.json"
    manifest.write_text(json.dumps({"commit": SHA, "release_tuple": {"middleware_image_digest": DIGEST}, "required_flags": {name: False for name in REQUIRED_FALSE_FLAGS}}))
    values = dict(action="preflight", sha=SHA, digest=DIGEST, change_id=CHANGE_ID, maintenance_date="2099-08-21", manifest=str(manifest))
    values.update(changes)
    return argparse.Namespace(**values)


def test_accepts_exact_fail_closed_tuple(tmp_path):
    validate(request(tmp_path))


@pytest.mark.parametrize("field,value", [("sha", "0" * 40), ("digest", "sha256:" + "0" * 64), ("change_id", "wrong"), ("maintenance_date", "")])
def test_rejects_mismatch_or_missing_date(tmp_path, field, value):
    with pytest.raises(ValueError):
        validate(request(tmp_path, **{field: value}))


def test_rejects_enabled_feature(tmp_path):
    args = request(tmp_path)
    manifest = json.loads(open(args.manifest, encoding="utf-8").read())
    manifest["required_flags"]["SEND_EVENTS"] = True
    with open(args.manifest, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream)
    with pytest.raises(ValueError):
        validate(args)


@pytest.mark.parametrize("flags", [None, {}, {"SEND_EVENTS": False}])
def test_rejects_missing_or_incomplete_fail_closed_flags(tmp_path, flags):
    args = request(tmp_path)
    manifest = json.loads(open(args.manifest, encoding="utf-8").read())
    manifest["required_flags"] = flags
    with open(args.manifest, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream)
    with pytest.raises(ValueError, match="incomplete fail-closed flags"):
        validate(args)


def test_rejects_non_boolean_false_flag(tmp_path):
    args = request(tmp_path)
    manifest = json.loads(open(args.manifest, encoding="utf-8").read())
    manifest["required_flags"]["SEND_EVENTS"] = 0
    with open(args.manifest, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream)
    with pytest.raises(ValueError, match="does not default fail closed"):
        validate(args)


@pytest.mark.parametrize("action", ["backup", "validate-backup", "restore-test", "stage", "canary", "rollback"])
def test_state_change_outside_window_fails_closed(tmp_path, action):
    with pytest.raises(ValueError, match="maintenance window"):
        validate(request(tmp_path, action=action, maintenance_date="2099-08-21"))


def test_manifest_must_bind_requested_digest(tmp_path):
    args = request(tmp_path, digest="sha256:" + "1" * 64)
    with pytest.raises(ValueError, match="manifest digest"):
        validate(args)
