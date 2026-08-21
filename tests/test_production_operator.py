from __future__ import annotations

import datetime as dt
import importlib.machinery
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "operations" / "production-operator"
OPERATOR_PATH = PACKAGE / "codestra-production-operator"
LOADER = importlib.machinery.SourceFileLoader("production_operator", str(OPERATOR_PATH))
SPEC = importlib.util.spec_from_loader("production_operator", LOADER)
OPERATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(OPERATOR)


EXPECTED_ACTIONS = {
    "preflight",
    "backup",
    "validate-backup",
    "restore-test",
    "stage",
    "canary",
    "status",
    "rollback",
    "collect-evidence",
}


def test_action_set_is_exact() -> None:
    assert OPERATOR.ALLOWED_ACTIONS == EXPECTED_ACTIONS
    assert OPERATOR.SYSTEMD_ACTIONS == {
        "backup": "codestra-backup.service",
        "validate-backup": "codestra-backup-state.service",
        "restore-test": "codestra-readiness-restore.service",
    }


@pytest.fixture(autouse=True)
def fixed_release_tuple(monkeypatch):
    monkeypatch.setattr(
        OPERATOR,
        "load_release_config",
        lambda: {
            "protected_sha": "e" * 40,
            "image_digest": "sha256:" + "3" * 64,
            "change_id": "CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01",
            "maintenance_date": "2026-08-22",
        },
    )


@pytest.mark.parametrize(
    "argv",
    [[], ["shell"], ["status", "extra"], ["../status"], ["status;id"], ["--help"]],
)
def test_extra_and_unsafe_arguments_fail_closed(monkeypatch, argv) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert OPERATOR.main(argv) == 2


def test_non_root_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert OPERATOR.main(["status"]) == 2


def test_maintenance_window_exact_boundary(monkeypatch) -> None:
    monkeypatch.setattr(
        OPERATOR,
        "checked_root_file",
        lambda path: "2026-08-22" if path == OPERATOR.MAINTENANCE_DATE else "",
    )
    before = dt.datetime(2026, 8, 22, 7, 59, tzinfo=dt.timezone.utc)
    assert OPERATOR.require_maintenance_window(before) == "2026-08-22"
    after = dt.datetime(2026, 8, 22, 8, 0, tzinfo=dt.timezone.utc)
    with pytest.raises(OPERATOR.OperatorError, match="outside approved"):
        OPERATOR.require_maintenance_window(after)


def test_maintenance_file_symlink_is_rejected(monkeypatch, tmp_path) -> None:
    real = tmp_path / "real"
    real.write_text("2026-08-22\n", encoding="ascii")
    real.chmod(0o600)
    link = tmp_path / "maintenance-date"
    link.symlink_to(real)
    monkeypatch.setattr(OPERATOR, "MAINTENANCE_DATE", link)
    with pytest.raises(OPERATOR.OperatorError, match="unsafe file type"):
        OPERATOR.require_maintenance_window()


def test_sudoers_enumerates_only_exact_actions() -> None:
    text = (PACKAGE / "codestra-production-operator.sudoers").read_text()
    assert "NOPASSWD: ALL" not in text
    commands = {
        line.rsplit(" ", 1)[-1]
        for line in text.splitlines()
        if "NOPASSWD:" in line
    }
    assert commands == EXPECTED_ACTIONS
    subprocess.run(
        ["visudo", "-cf", str(PACKAGE / "codestra-production-operator.sudoers")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_forced_command_has_no_eval_or_shell_dispatch() -> None:
    text = (PACKAGE / "codestra-production-forced-command").read_text()
    assert "eval" not in text
    assert "sh -c" not in text
    assert "bash -c" not in text
    subprocess.run(["sh", "-n", str(PACKAGE / "codestra-production-forced-command")], check=True)


def test_forced_command_rejects_unrestricted_session() -> None:
    result = subprocess.run(
        ["sh", str(PACKAGE / "codestra-production-forced-command")],
        env={"SSH_ORIGINAL_COMMAND": "status; /bin/sh"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "allowlisted action" in result.stderr


def test_status_action_has_positive_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        OPERATOR,
        "safety_state",
        lambda: {
            "telephony_probe_pass": True,
            "active_calls_zero": True,
            "active_channels_zero": True,
            "required_runtime_flags_false": True,
            "sip_registration_performed": False,
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "run_fixed",
        lambda _command: subprocess.CompletedProcess(_command, 0, "", ""),
    )
    code, result = OPERATOR.execute("status")
    assert code == 0
    assert result["returncode"] == 0


@pytest.mark.parametrize("missing_or_enabled", [None, "true"])
def test_runtime_safety_flags_fail_closed(monkeypatch, missing_or_enabled) -> None:
    safe_entries = [f"{name}=false" for name in OPERATOR.CANONICAL_FALSE_FLAGS]
    if missing_or_enabled is None:
        safe_entries.pop()
    else:
        safe_entries[-1] = safe_entries[-1].partition("=")[0] + f"={missing_or_enabled}"

    def fake_run(command):
        if command[-1] == "core show channels count":
            return subprocess.CompletedProcess(command, 0, "0 active channels\n0 active calls\n", "")
        if command[-1] == "pjsip show registrations":
            return subprocess.CompletedProcess(command, 0, "No objects found.\n", "")
        if command[:2] == ["/usr/bin/docker", "inspect"]:
            import json

            return subprocess.CompletedProcess(command, 0, json.dumps(safe_entries), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(OPERATOR, "run_fixed", fake_run)
    state = OPERATOR.safety_state()
    assert state["required_runtime_flags_false"] is False


@pytest.mark.parametrize("count", [1, 10, 20, 100])
def test_nonzero_asterisk_counters_never_match_zero(monkeypatch, count) -> None:
    safe_entries = [f"{name}=false" for name in OPERATOR.CANONICAL_FALSE_FLAGS]

    def fake_run(command):
        if command[-1] == "core show channels count":
            output = f"{count} active channels\n{count} active calls\n"
            return subprocess.CompletedProcess(command, 0, output, "")
        if command[-1] == "pjsip show registrations":
            return subprocess.CompletedProcess(command, 0, "No objects found.\n", "")
        if command[:2] == ["/usr/bin/docker", "inspect"]:
            import json

            return subprocess.CompletedProcess(command, 0, json.dumps(safe_entries), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(OPERATOR, "run_fixed", fake_run)
    state = OPERATOR.safety_state()
    assert state["active_calls_zero"] is False
    assert state["active_channels_zero"] is False


@pytest.mark.parametrize("action", ["status", "collect-evidence"])
def test_diagnostics_and_rollback_remain_available_when_unsafe(monkeypatch, action) -> None:
    monkeypatch.setattr(
        OPERATOR,
        "safety_state",
        lambda: {
            "telephony_probe_pass": False,
            "active_calls_zero": False,
            "active_channels_zero": False,
            "required_runtime_flags_false": False,
            "sip_registration_performed": True,
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "run_fixed",
        lambda command: subprocess.CompletedProcess(command, 0, "", ""),
    )
    code, result = OPERATOR.execute(action)
    assert code == 0
    assert result["returncode"] == 0


def test_rollback_remains_available_when_unsafe(monkeypatch) -> None:
    monkeypatch.setattr(
        OPERATOR,
        "safety_state",
        lambda: {
            "telephony_probe_pass": False,
            "active_calls_zero": False,
            "active_channels_zero": False,
            "required_runtime_flags_false": False,
            "sip_registration_performed": True,
        },
    )
    monkeypatch.setattr(OPERATOR, "remove_standby", lambda _config: {"candidate_present": False})
    code, result = OPERATOR.execute("rollback")
    assert code == 0
    assert result["candidate_present"] is False


def test_preflight_rejects_unsafe_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        OPERATOR,
        "safety_state",
        lambda: {
            "telephony_probe_pass": True,
            "active_calls_zero": False,
            "active_channels_zero": True,
            "required_runtime_flags_false": True,
            "sip_registration_performed": False,
        },
    )
    with pytest.raises(OPERATOR.OperatorError, match="not fail-closed"):
        OPERATOR.execute("preflight")


@pytest.mark.parametrize(
    "name",
    [
        "install-server-a-operator.sh",
        "remove-server-a-operator.sh",
        "validate-server-a-operator.sh",
        "codestra-production-forced-command",
    ],
)
def test_shell_artifacts_have_valid_syntax(name) -> None:
    subprocess.run(["sh", "-n", str(PACKAGE / name)], check=True)


def test_payload_checksums_are_real() -> None:
    installer = (PACKAGE / "install-server-a-operator.sh").read_text()
    for name in (
        "codestra-production-operator",
        "codestra-production-forced-command",
        "codestra-production-operator.sudoers",
        "codestra-production-operator.sshd",
    ):
        digest = subprocess.check_output(["sha256sum", str(PACKAGE / name)], text=True).split()[0]
        assert f"{digest}  {name}" in installer


def test_forced_command_binds_exact_release_tuple_before_sudo() -> None:
    text = (PACKAGE / "codestra-production-forced-command").read_text()
    assert 'path = "/etc/codestra/production-operator/release.json"' in text
    assert "parts[1:] != expected" in text
    assert 'exec /usr/bin/sudo -n /usr/local/sbin/codestra-production-operator "$action"' in text


def test_stage_uses_exact_digest_and_isolated_standby() -> None:
    text = OPERATOR_PATH.read_text()
    assert 'subject = f"{MIDDLEWARE_IMAGE}@{config[' + "'image_digest'" + ']}"' in text
    assert '"--network", "none"' in text
    assert '"--read-only", "--cap-drop", "ALL"' in text
    assert '"ENABLE_EXTERNAL_DELIVERY=false"' in text
    assert 'subject not in image.get("RepoDigests", [])' in text


def test_workflow_uses_restricted_pinned_operator_transport() -> None:
    workflow = (ROOT / ".github/workflows/production-activation.yml").read_text()
    assert "secrets.CODESTRA_PRODUCTION_OPERATOR_SSH_KEY" in workflow
    assert "secrets.CODESTRA_PRODUCTION_OPERATOR_KNOWN_HOSTS" in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    assert "ClearAllForwardings=yes" in workflow
    assert "PasswordAuthentication=no" in workflow
    assert "test \"${OPERATOR_USER}\" = 'codestra-production-operator'" in workflow
    assert "scp " not in workflow
    assert "rsync " not in workflow
