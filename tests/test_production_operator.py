import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).parents[1] / "operations/production-operator/codestra-production-operator.py"
SPEC = importlib.util.spec_from_file_location("production_operator", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

SHA = "e" * 40
DIGEST = "sha256:" + "3" * 64
CHANGE = "CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01"
DATE = "2026-08-22"


def test_exact_allowlist() -> None:
    assert MODULE.ALLOWED == {
        "preflight", "backup", "validate-backup", "restore-test", "stage",
        "canary", "status", "rollback", "collect-evidence",
    }


@pytest.mark.parametrize("action", sorted(MODULE.ALLOWED))
def test_valid_direct_command(action: str) -> None:
    assert MODULE.parse([action, SHA, DIGEST, CHANGE, DATE])[0] == action


@pytest.mark.parametrize("action", ["shell", "exec", "install", "stage;id", "", "../status"])
def test_unknown_action_denied(action: str) -> None:
    with pytest.raises(MODULE.Denied):
        MODULE.parse([action, SHA, DIGEST, CHANGE, DATE])


@pytest.mark.parametrize("bad", ["main", "a" * 39, "A" * 40, "a" * 41, "../../etc/passwd"])
def test_invalid_sha_denied(bad: str) -> None:
    with pytest.raises(MODULE.Denied):
        MODULE.parse(["status", bad, DIGEST, CHANGE, DATE])


@pytest.mark.parametrize("bad", ["latest", "sha256:123", "sha512:" + "a" * 64, "sha256:" + "g" * 64])
def test_invalid_digest_denied(bad: str) -> None:
    with pytest.raises(MODULE.Denied):
        MODULE.parse(["status", SHA, bad, CHANGE, DATE])


def test_forced_command_rejects_shell_syntax(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", f"status {SHA} {DIGEST} {CHANGE} {DATE};id")
    with pytest.raises(MODULE.Denied):
        MODULE.parse(["forced"])


def test_forced_command_accepts_only_exact_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", f"status {SHA} {DIGEST} {CHANGE} {DATE}")
    assert MODULE.parse(["forced"])[0] == "status"


def test_release_tuple_mismatch_denied() -> None:
    request = MODULE.parse(["status", SHA, DIGEST, CHANGE, DATE])
    config = {"protected_sha": "f" * 40, "image_digest": DIGEST, "change_id": CHANGE, "maintenance_date": DATE}
    with pytest.raises(MODULE.Denied):
        MODULE.bind(request, config)


def test_fixed_environment_excludes_inherited_secrets() -> None:
    assert set(MODULE.FIXED_ENV) == {"PATH", "LANG", "LC_ALL"}
    assert not any("TOKEN" in key or "SECRET" in key for key in MODULE.FIXED_ENV)


def test_installer_has_restricted_forced_command_and_no_nopasswd_all() -> None:
    text = (PATH.parent / "install.sh").read_text()
    assert 'codestra-production-operator forced' in text
    assert 'restrict,command=' in text
    assert "NOPASSWD: ALL" not in text
    assert "SSH_ORIGINAL_COMMAND" in text
    assert "authorized_keys may not be a symlink" in text


def test_stage_verifies_exact_repo_digest_and_uses_network_none() -> None:
    text = PATH.read_text()
    assert 'item == subject for item in image.get("RepoDigests", [])' in text
    assert '"--network", "none"' in text
    assert '"PSTN_DIALING=DISABLED"' in text
    assert '"ENABLE_EXTERNAL_DELIVERY=false"' in text
