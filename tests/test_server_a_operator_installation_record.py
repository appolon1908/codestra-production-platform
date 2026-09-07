from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
RECORD = ROOT / "config/server-a-operator-installation-record.json"
VALIDATOR_PATH = ROOT / "tools/validate_server_a_operator_installation_record.py"
spec = importlib.util.spec_from_file_location("installation_record", VALIDATOR_PATH)
assert spec and spec.loader
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def record() -> dict:
    return json.loads(RECORD.read_text())


def complete() -> dict:
    value = record()
    value["status"] = "approved"
    value["target_release"] = {
        "protected_commit": "a" * 40,
        "release_archive_sha256": "b" * 64,
        "release_manifest_sha256": "c" * 64,
        "installer_sha256": "d" * 64,
        "approval": "independent protected review",
    }
    value["operator_public_key_fingerprint"] = {
        "value": "SHA256:" + "A" * 43,
        "source": "root owner fingerprint read-back",
        "approval": "owner approval",
    }
    values = {
        "operator_public_key": "/home/codestra-admin/operator-current.ABC123.pub",
        "protected_commit": "a" * 40,
        "image_digest": "sha256:" + "e" * 64,
        "change_id": "CHG-20260907-CODESTRA-PRODUCTION-ACTIVATION-02",
        "maintenance_date": "2026-09-08",
        "control_plane_archive_sha256": "f" * 64,
    }
    for name, item in value["arguments"].items():
        item.update(value=values[name], source=f"approved {name} authority", approval="owner approval")
    return value


def test_committed_record_is_valid_but_explicitly_incomplete() -> None:
    assert validator.validate(record(), require_approved=False) == []


def test_complete_record_accepts_six_authoritative_arguments() -> None:
    assert validator.validate(complete()) == []


def test_missing_value_or_approval_fails_closed() -> None:
    for field in validator.FIELDS:
        candidate = complete()
        candidate["arguments"][field]["approval"] = None
        assert any(field in error for error in validator.validate(candidate))
    candidate = complete()
    candidate["operator_public_key_fingerprint"]["approval"] = None
    assert any("fingerprint" in error for error in validator.validate(candidate))


def test_control_plane_digest_cannot_be_substituted() -> None:
    candidate = complete()
    candidate["arguments"]["control_plane_archive_sha256"]["value"] = candidate["target_release"]["installer_sha256"]
    candidate["arguments"]["control_plane_archive_sha256"]["source"] = "operator installer checksum"
    assert any("control-plane archive" in error for error in validator.validate(candidate))


def test_launcher_is_zero_argument_and_preserve_only() -> None:
    launcher = (ROOT / "operations/production-operator/launch-reviewed-installation.sh").read_text()
    assert '[ "$#" -eq 0 ]' in launcher
    assert "--preserve-existing-sudoers" in launcher
    assert "ssh-keygen -lf" in launcher
    assert "sudo " not in launcher
