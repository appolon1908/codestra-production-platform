import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "operations/readiness/hetzner_restic_preflight.py"
SPEC = importlib.util.spec_from_file_location("hetzner_restic_preflight", SOURCE)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.fixture
def secure_directory(tmp_path):
    # Model the ambient CI ancestors as trusted; hosted runners may use
    # shared directories. The fixture directory and all descendants retain
    # their real modes/owners, including the unsafe-ancestor regression cases.
    ancestors = {(item.stat().st_dev, item.stat().st_ino) for item in tmp_path.parents}
    original_fstat = os.fstat

    def controlled_ancestors(descriptor):
        info = original_fstat(descriptor)
        if (info.st_dev, info.st_ino) in ancestors:
            return SimpleNamespace(st_mode=info.st_mode & ~0o022, st_uid=0,
                                   st_dev=info.st_dev, st_ino=info.st_ino)
        return info

    with patch.object(preflight.os, "fstat", side_effect=controlled_ancestors):
        yield tmp_path


@pytest.fixture
def profile(secure_directory):
    tmp_path = secure_directory
    values = {"schema_version": 1, "region": "fsn1",
              "bucket": "codestra-test-backups", "prefix": "codestra/production"}
    for name in ("access_key_id_file", "secret_access_key_file", "restic_password_file"):
        path = tmp_path / name
        path.write_text("synthetic-test-credential-" + name + "\n")
        path.chmod(0o600)
        values[name] = str(path)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(values))
    path.chmod(0o600)
    return path, values


def update(profile, **changes):
    path, values = profile
    values.update(changes)
    path.write_text(json.dumps(values))
    return path


def test_validation_does_not_contact_storage_or_claim_cutover(profile):
    with patch.object(preflight.subprocess, "run") as run:
        result = preflight.inspect_profile(profile[0])
    run.assert_not_called()
    assert result["repository"] == (
        "s3:https://fsn1.your-objectstorage.com/codestra-test-backups/codestra/production")
    assert result["repository_access"] == "not_checked"
    assert not any(result[key] for key in ("cutover_performed", "upload_verified", "restore_verified"))


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"region": "fsn1.attacker.invalid"},
    {"bucket": "bucket@attacker.invalid"}, {"bucket": "REPLACE_WITH_PRIVATE_BUCKET"},
    {"prefix": "../other"}, {"prefix": "codestra?secret=x"},
    {"prefix": ""}, {"prefix": "codestra//prod"},
    {"secret_access_key_file": "../secret"}, {"region": ["fsn1"]},
    {"endpoint": "http://untrusted.invalid"},
])
def test_invalid_destinations_and_unexpected_fields_are_rejected_before_network(profile, change):
    path = update(profile, **change)
    with patch.object(preflight.subprocess, "run") as run, pytest.raises(preflight.ProfileError):
        preflight.inspect_profile(path, True)
    run.assert_not_called()


def test_duplicate_json_keys_are_rejected(profile):
    profile[0].write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(preflight.ProfileError, match="duplicate_profile_field"):
        preflight.load_profile(profile[0])


@pytest.mark.parametrize("kind", ["missing", "empty", "readable", "symlink", "directory"])
def test_missing_or_unsafe_credentials_are_rejected(profile, kind, secure_directory):
    tmp_path = secure_directory
    path = Path(profile[1]["secret_access_key_file"])
    if kind == "missing":
        path.unlink()
    elif kind == "empty":
        path.write_text("")
    elif kind == "readable":
        path.chmod(0o644)
    elif kind == "symlink":
        target = tmp_path / "target"
        path.rename(target)
        path.symlink_to(target)
    else:
        path.unlink()
        path.mkdir()
    with patch.object(preflight.subprocess, "run") as run, pytest.raises(preflight.ProfileError):
        preflight.inspect_profile(profile[0], True)
    run.assert_not_called()


def test_environment_is_isolated_and_metadata_is_not_printed(profile):
    secret = "synthetic-test-credential-secret_access_key_file"
    response = subprocess.CompletedProcess([], 0, json.dumps([
        {"id": "a" * 64, "paths": ["/sensitive/customer/data"], "hostname": "private"}
    ]), "")
    poisoned = {"AWS_SESSION_TOKEN": "old-token", "RESTIC_PASSWORD_COMMAND": "untrusted",
                "AWS_ENDPOINT_URL": "https://untrusted.invalid", "HTTPS_PROXY": "untrusted"}
    with patch.dict(os.environ, poisoned), patch.object(
            preflight.subprocess, "run", return_value=response) as run:
        result = preflight.inspect_profile(profile[0], True)
    args, kwargs = run.call_args
    assert args[0] == ["/usr/bin/restic", "--no-cache", "--no-lock", "snapshots", "--json"]
    assert kwargs["env"]["AWS_SECRET_ACCESS_KEY"] == secret
    assert kwargs["env"]["RESTIC_PASSWORD"] == "synthetic-test-credential-restic_password_file"
    assert "RESTIC_PASSWORD_FILE" not in kwargs["env"]
    assert set(kwargs["env"]).isdisjoint(poisoned)
    assert result["repository_access"] == "readable"
    assert result["snapshot_count"] == 1
    assert secret not in json.dumps(result)
    assert "/sensitive/customer/data" not in json.dumps(result)


@pytest.mark.parametrize("response", [
    subprocess.CompletedProcess([], 1, "", "synthetic-secret must not escape"),
    subprocess.CompletedProcess([], 0, "not-json synthetic-secret", ""),
    subprocess.CompletedProcess([], 0, '{"items":[]}', ""),
    subprocess.CompletedProcess([], 0, '[{"id":null}]', ""),
])
def test_failed_or_malformed_repository_read_is_not_success(profile, response):
    with patch.object(preflight.subprocess, "run", return_value=response):
        result = preflight.inspect_profile(profile[0], True)
    assert result["repository_access"] == "failed"
    assert "synthetic-secret" not in json.dumps(result)
    assert result["cutover_performed"] is False


def test_timeout_is_bounded_and_does_not_expose_child_environment(profile):
    with patch.object(preflight.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired("restic", 30)):
        result = preflight.inspect_profile(profile[0], True)
    assert result["reason"] == "repository_probe_unavailable_or_timeout"


def test_empty_initialized_repository_is_readable_but_not_restore_proof(profile):
    with patch.object(preflight.subprocess, "run",
                      return_value=subprocess.CompletedProcess([], 0, "[]", "")):
        result = preflight.inspect_profile(profile[0], True)
    assert result["repository_access"] == "readable"
    assert result["snapshot_count"] == 0
    assert result["restore_verified"] is False


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777])
def test_public_or_writable_parent_directory_is_rejected(profile, mode):
    directory = profile[0].parent
    directory.chmod(mode)
    try:
        with patch.object(preflight.subprocess, "run") as run, pytest.raises(
                preflight.ProfileError, match="unsafe_protected_directory"):
            preflight.inspect_profile(profile[0], True)
        run.assert_not_called()
    finally:
        directory.chmod(0o700)


def test_writable_ancestor_is_rejected_even_when_immediate_parent_is_private(profile):
    ancestor = profile[0].parent / "shared"
    ancestor.mkdir(mode=0o777)
    ancestor.chmod(0o777)
    private = ancestor / "private"
    private.mkdir(mode=0o700)
    credential = private / "credential"
    credential.write_text("synthetic-test-only")
    credential.chmod(0o600)
    path = update(profile, secret_access_key_file=str(credential))
    with patch.object(preflight.subprocess, "run") as run, pytest.raises(
            preflight.ProfileError, match="unsafe_protected_directory"):
        preflight.inspect_profile(path, True)
    run.assert_not_called()


def test_symlink_ancestor_is_rejected(profile):
    directory = profile[0].parent
    real = directory / "real"
    real.mkdir(mode=0o700)
    link = directory / "alias"
    link.symlink_to(real, target_is_directory=True)
    credential = real / "credential"
    credential.write_text("synthetic-test-only")
    credential.chmod(0o600)
    path = update(profile, secret_access_key_file=str(link / "credential"))
    with patch.object(preflight.subprocess, "run") as run, pytest.raises(preflight.ProfileError):
        preflight.inspect_profile(path, True)
    run.assert_not_called()


def test_foreign_owned_parent_is_rejected(profile):
    directory_info = profile[0].parent.stat()
    original_fstat = os.fstat

    def foreign_owner(descriptor):
        info = original_fstat(descriptor)
        if (info.st_dev, info.st_ino) == (directory_info.st_dev, directory_info.st_ino):
            return SimpleNamespace(st_mode=info.st_mode, st_uid=os.geteuid() + 100000)
        return info

    with patch.object(preflight.os, "fstat", side_effect=foreign_owner), patch.object(
            preflight.subprocess, "run") as run, pytest.raises(
                preflight.ProfileError, match="unsafe_protected_directory"):
        preflight.inspect_profile(profile[0], True)
    run.assert_not_called()


def test_child_uses_validated_password_without_reopening_path(profile):
    password_path = Path(profile[1]["restic_password_file"])
    validated_password = password_path.read_text().strip()

    def read_repository(args, **kwargs):
        password_path.write_text("changed-after-validation")
        assert kwargs["env"]["RESTIC_PASSWORD"] == validated_password
        assert "RESTIC_PASSWORD_FILE" not in kwargs["env"]
        return subprocess.CompletedProcess(args, 0, "[]", "")

    with patch.object(preflight.subprocess, "run", side_effect=read_repository):
        result = preflight.inspect_profile(profile[0], True)
    assert result["repository_access"] == "readable"
    assert validated_password not in json.dumps(result)
