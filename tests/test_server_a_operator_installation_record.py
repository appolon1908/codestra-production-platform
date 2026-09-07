from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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
        "launcher_sha256": "1" * 64,
        "embedded_installation_record_sha256": "2" * 64,
        "trust_anchor_sha256": "3" * 64,
        "manifest_signature_verified": True,
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


def test_nonexistent_maintenance_date_is_rejected() -> None:
    candidate = complete()
    candidate["arguments"]["maintenance_date"]["value"] = "2026-02-31"
    assert any("calendar date" in error for error in validator.validate(candidate))


def test_launcher_is_zero_argument_and_preserve_only() -> None:
    launcher = (ROOT / "operations/production-operator/launch-reviewed-installation.sh").read_text()
    assert '[ "$#" -eq 0 ]' in launcher
    assert "--preserve-existing-sudoers" in launcher
    assert "ssh-keygen -lf" in launcher
    assert "sudo " not in launcher


# Exercise the Python/CLI authority actually used by the root launcher. No
# installer, SSH session, live key or production host is touched by these tests.
NON_BOOLEAN_SIGNATURE_VALUES = ["false", "true", "", 0, 1, 0.0, 1.0, [], [True], {}, {"verified": True}]
TARGET_DIGEST_FIELDS = (
    "release_archive_sha256",
    "release_manifest_sha256",
    "installer_sha256",
    "launcher_sha256",
    "embedded_installation_record_sha256",
    "trust_anchor_sha256",
)


def run_validator(candidate: dict, tmp_path: Path, *, allow_incomplete: bool = False) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "installation-record.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    command = [sys.executable, str(VALIDATOR_PATH), str(path)]
    if allow_incomplete:
        command.append("--allow-incomplete")
    return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)


@pytest.mark.parametrize("value", [False, None, *NON_BOOLEAN_SIGNATURE_VALUES])
def test_approved_signature_requires_literal_true(value: object, tmp_path: Path) -> None:
    candidate = complete()
    candidate["target_release"]["manifest_signature_verified"] = value
    assert any("manifest_signature_verified" in error for error in validator.validate(candidate))
    result = run_validator(candidate, tmp_path)
    assert result.returncode == 2
    assert "manifest_signature_verified" in result.stdout
    assert "INSTALLATION_RECORD_STATUS=APPROVED" not in result.stdout


def test_approved_signature_cannot_be_omitted(tmp_path: Path) -> None:
    candidate = complete()
    del candidate["target_release"]["manifest_signature_verified"]
    assert any("manifest_signature_verified" in error for error in validator.validate(candidate))
    assert run_validator(candidate, tmp_path).returncode == 2


@pytest.mark.parametrize("value", NON_BOOLEAN_SIGNATURE_VALUES)
def test_incomplete_record_rejects_non_boolean_signature(value: object, tmp_path: Path) -> None:
    candidate = record()
    candidate["target_release"]["manifest_signature_verified"] = value
    assert any("manifest_signature_verified" in error for error in validator.validate(candidate, require_approved=False))
    assert run_validator(candidate, tmp_path, allow_incomplete=True).returncode == 2


@pytest.mark.parametrize("value", [None, False, True])
def test_incomplete_record_allows_only_boolean_or_null_signature(value: object, tmp_path: Path) -> None:
    candidate = record()
    candidate["target_release"]["manifest_signature_verified"] = value
    assert validator.validate(candidate, require_approved=False) == []
    result = run_validator(candidate, tmp_path, allow_incomplete=True)
    assert result.returncode == 0
    assert "INSTALLATION_RECORD_STATUS=INCOMPLETE" in result.stdout
    assert run_validator(candidate, tmp_path).returncode == 2


@pytest.mark.parametrize("field", tuple(field for field in TARGET_DIGEST_FIELDS if field != "release_archive_sha256"))
@pytest.mark.parametrize("require_approved", [False, True])
def test_every_target_digest_is_rejected_as_control_plane(field: str, require_approved: bool, tmp_path: Path) -> None:
    candidate = complete()
    candidate["status"] = "approved" if require_approved else "incomplete"
    control = candidate["arguments"]["control_plane_archive_sha256"]
    control["value"] = candidate["target_release"][field]
    # Use neutral provenance so this test cannot pass solely on the source-text guard.
    control["source"] = "independently supplied archive bytes"
    assert any("control-plane archive" in error for error in validator.validate(candidate, require_approved=require_approved))
    result = run_validator(candidate, tmp_path, allow_incomplete=not require_approved)
    assert result.returncode == 2
    assert "control-plane archive" in result.stdout


@pytest.mark.parametrize("require_approved", [False, True])
def test_image_digest_is_not_control_plane_archive(require_approved: bool, tmp_path: Path) -> None:
    candidate = complete()
    candidate["status"] = "approved" if require_approved else "incomplete"
    candidate["arguments"]["control_plane_archive_sha256"]["value"] = candidate["arguments"]["image_digest"]["value"].removeprefix("sha256:")
    assert any("control-plane archive" in error for error in validator.validate(candidate, require_approved=require_approved))
    assert run_validator(candidate, tmp_path, allow_incomplete=not require_approved).returncode == 2


def test_signed_platform_archive_is_the_control_plane_archive(tmp_path: Path) -> None:
    candidate = complete()
    digest = candidate["target_release"]["release_archive_sha256"]
    control = candidate["arguments"]["control_plane_archive_sha256"]
    control["value"] = digest
    control["source"] = "immutable GitHub release asset bound by deployment-manifest.json and provenance.json"
    assert validator.validate(candidate) == []
    assert run_validator(candidate, tmp_path).returncode == 0


def test_release_archive_reuse_requires_explicit_provenance(tmp_path: Path) -> None:
    candidate = complete()
    candidate["arguments"]["control_plane_archive_sha256"].update(
        value=candidate["target_release"]["release_archive_sha256"],
        source="some local archive",
    )
    assert any("signed release provenance" in error for error in validator.validate(candidate))
    assert run_validator(candidate, tmp_path).returncode == 2


def test_cli_accepts_complete_fixture_and_keeps_committed_record_incomplete(tmp_path: Path) -> None:
    result = run_validator(complete(), tmp_path)
    assert result.returncode == 0
    assert "INSTALLATION_RECORD_STATUS=APPROVED" in result.stdout
    assert run_validator(record(), tmp_path).returncode == 2
    result = run_validator(record(), tmp_path, allow_incomplete=True)
    assert result.returncode == 0
    assert "INSTALLATION_RECORD_STATUS=INCOMPLETE" in result.stdout
