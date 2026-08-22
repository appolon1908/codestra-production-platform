from __future__ import annotations

import datetime as dt
import hashlib
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
        "backup": "codestra-readiness-backup.service",
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
    assert OPERATOR.require_maintenance_window(before)["window_check"] == "APPROVED_WINDOW"
    after = dt.datetime(2026, 8, 22, 8, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(
        OPERATOR,
        "validate_owner_window_waiver",
        lambda: {
            "maintenance_window": "WAIVED_BY_OWNER",
            "owner_window_waiver_evidence": "PASS",
            "window_check": "BYPASSED_BY_VALID_OWNER_WAIVER",
        },
    )
    assert OPERATOR.require_maintenance_window(after)["window_check"] == "BYPASSED_BY_VALID_OWNER_WAIVER"


def _waiver_files(tmp_path: Path, monkeypatch, content: str | None = None) -> tuple[Path, Path]:
    waiver = tmp_path / "OWNER-MAINTENANCE-WINDOW-WAIVER.txt"
    checksum = tmp_path / "OWNER-MAINTENANCE-WINDOW-WAIVER.sha256"
    body = content or "\n".join(sorted(OPERATOR.OWNER_WINDOW_WAIVER_STATEMENTS)) + "\n"
    waiver.write_text(body, encoding="ascii")
    digest = __import__("hashlib").sha256(body.encode("ascii")).hexdigest()
    checksum.write_text(f"{digest}  {waiver.name}\n", encoding="ascii")
    waiver.chmod(0o600)
    checksum.chmod(0o600)
    real_fstat = os.fstat

    def root_owned_fstat(descriptor):
        info = real_fstat(descriptor)
        return type(
            "RootOwnedStat",
            (),
            {"st_mode": info.st_mode, "st_uid": 0, "st_gid": 0},
        )()

    monkeypatch.setattr(OPERATOR.os, "fstat", root_owned_fstat)
    monkeypatch.setattr(OPERATOR, "OWNER_WAIVER_DIR", tmp_path)
    monkeypatch.setattr(OPERATOR, "OWNER_WINDOW_WAIVER", waiver)
    monkeypatch.setattr(OPERATOR, "OWNER_WINDOW_WAIVER_CHECKSUM", checksum)
    return waiver, checksum


def test_outside_window_without_waiver_is_denied(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(OPERATOR, "OWNER_WAIVER_DIR", tmp_path)
    monkeypatch.setattr(OPERATOR, "OWNER_WINDOW_WAIVER", tmp_path / "OWNER-MAINTENANCE-WINDOW-WAIVER.txt")
    monkeypatch.setattr(OPERATOR, "OWNER_WINDOW_WAIVER_CHECKSUM", tmp_path / "OWNER-MAINTENANCE-WINDOW-WAIVER.sha256")
    with pytest.raises(OPERATOR.OperatorError, match="unavailable"):
        OPERATOR.validate_owner_window_waiver()


def test_valid_owner_waiver_is_allowed(monkeypatch, tmp_path) -> None:
    _waiver_files(tmp_path, monkeypatch)
    result = OPERATOR.validate_owner_window_waiver()
    assert result["maintenance_window"] == "WAIVED_BY_OWNER"
    assert result["window_check"] == "BYPASSED_BY_VALID_OWNER_WAIVER"


def test_malformed_owner_waiver_is_denied(monkeypatch, tmp_path) -> None:
    _waiver_files(tmp_path, monkeypatch, "MAINTENANCE_WINDOW=WAIVED_BY_OWNER\n")
    with pytest.raises(OPERATOR.OperatorError, match="statements"):
        OPERATOR.validate_owner_window_waiver()


def test_wrong_owner_waiver_checksum_is_denied(monkeypatch, tmp_path) -> None:
    _, checksum = _waiver_files(tmp_path, monkeypatch)
    checksum.write_text(f"{'0' * 64}  OWNER-MAINTENANCE-WINDOW-WAIVER.txt\n", encoding="ascii")
    with pytest.raises(OPERATOR.OperatorError, match="checksum mismatch"):
        OPERATOR.validate_owner_window_waiver()


def test_owner_waiver_checksum_covers_exact_bytes(monkeypatch, tmp_path) -> None:
    waiver, checksum = _waiver_files(tmp_path, monkeypatch)
    exact = waiver.read_bytes().rstrip(b"\n")
    waiver.write_bytes(exact)
    normalized_digest = __import__("hashlib").sha256(exact + b"\n").hexdigest()
    checksum.write_text(
        f"{normalized_digest}  OWNER-MAINTENANCE-WINDOW-WAIVER.txt\n",
        encoding="ascii",
    )
    with pytest.raises(OPERATOR.OperatorError, match="checksum mismatch"):
        OPERATOR.validate_owner_window_waiver()


def test_unsafe_owner_waiver_permissions_are_denied(monkeypatch, tmp_path) -> None:
    waiver, _ = _waiver_files(tmp_path, monkeypatch)
    waiver.chmod(0o660)
    with pytest.raises(OPERATOR.OperatorError, match="unsafe mode"):
        OPERATOR.validate_owner_window_waiver()


def test_non_root_owner_waiver_is_denied(monkeypatch, tmp_path) -> None:
    _waiver_files(tmp_path, monkeypatch)
    monkeypatch.setattr(
        OPERATOR.os,
        "fstat",
        lambda _descriptor: type(
            "UnprivilegedStat",
            (),
            {"st_mode": 0o100600, "st_uid": 1000, "st_gid": 1000},
        )(),
    )
    with pytest.raises(OPERATOR.OperatorError, match="unsafe ownership"):
        OPERATOR.validate_owner_window_waiver()


def test_owner_waiver_symlink_is_denied(monkeypatch, tmp_path) -> None:
    waiver, _ = _waiver_files(tmp_path, monkeypatch)
    target = tmp_path / "target"
    waiver.rename(target)
    waiver.symlink_to(target)
    with pytest.raises(OPERATOR.OperatorError, match="unsafe file type"):
        OPERATOR.validate_owner_window_waiver()


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


def test_vicidial_probe_uses_restricted_absolute_asterisk_command(monkeypatch) -> None:
    commands = []
    safe_entries = [f"{name}=false" for name in OPERATOR.CANONICAL_FALSE_FLAGS]

    def fake_run(command):
        commands.append(command)
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

    assert state["telephony_probe_pass"] is True
    assert commands[:2] == [
        [
            "/usr/bin/ssh",
            "codestra-vicidial",
            "/usr/bin/sudo -n /usr/sbin/asterisk -rx 'core show channels count'",
        ],
        [
            "/usr/bin/ssh",
            "codestra-vicidial",
            "/usr/bin/sudo -n /usr/sbin/asterisk -rx 'pjsip show registrations'",
        ],
    ]


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

    assert "-g codestra-production-operator -m 0710" in installer
    assert installer.index("useradd --system") < installer.index(
        "-g codestra-production-operator -m 0710"
    )
    assert "state_dir_uid=$(stat -c %u \"$state_dir\")" in installer
    assert "state_dir_gid=$(stat -c %g \"$state_dir\")" in installer
    assert "state_dir_mode=$(stat -c %a \"$state_dir\")" in installer
    assert 'chown "$state_dir_uid:$state_dir_gid" "$state_dir"' in installer
    assert 'chmod "$state_dir_mode" "$state_dir"' in installer


def test_validator_proves_authorized_key_is_readable_by_operator():
    validator = (PACKAGE / "validate-server-a-operator.sh").read_text()

    assert "root:codestra-production-operator 710" in validator
    assert "codestra-production-operator:codestra-production-operator 700" in validator
    assert "codestra-production-operator:codestra-production-operator 600" in validator
    assert "sudo -u codestra-production-operator" in validator
    assert "test -r /var/lib/codestra-production-operator/.ssh/authorized_keys" in validator


def test_forced_command_binds_exact_release_tuple_before_sudo() -> None:
    text = (PACKAGE / "codestra-production-forced-command").read_text()
    assert 'path = "/etc/codestra/production-operator/release.json"' in text
    assert "parts[1:] != expected" in text
    assert 'exec /usr/bin/sudo -n /usr/local/sbin/codestra-production-operator "$action"' in text


def test_waiver_cannot_bypass_tuple_or_protected_approval() -> None:
    forced = (PACKAGE / "codestra-production-forced-command").read_text()
    workflow = (ROOT / ".github/workflows/production-activation.yml").read_text()
    assert 'parts[1:] != expected' in forced
    assert 'test "$(git rev-parse HEAD)" = "${PROTECTED_SHA}"' in workflow
    assert 'test "$(gh api "repos/${GITHUB_REPOSITORY}/branches/release%2Fproduction-activation" --jq .commit.sha)" = "${PROTECTED_SHA}"' in workflow
    assert '--digest "${IMAGE_DIGEST}"' in workflow
    assert "environment: production" in workflow
    assert "OWNER_WINDOW_WAIVER" not in workflow


def test_stage_uses_exact_digest_and_isolated_standby() -> None:
    text = OPERATOR_PATH.read_text()
    assert 'subject = f"{MIDDLEWARE_IMAGE}@{config[' + "'image_digest'" + ']}"' in text
    assert '"--network", "none"' in text
    assert '"--read-only", "--cap-drop", "ALL"' in text
    assert '"ENABLE_EXTERNAL_DELIVERY=false"' in text
    assert 'subject not in image.get("RepoDigests", [])' in text


def test_backup_actions_use_installed_fixed_paths() -> None:
    text = OPERATOR_PATH.read_text()
    assert '"backup": "codestra-readiness-backup.service"' in text
    assert '"restore-test": "codestra-readiness-restore.service"' in text
    assert 'Path("/opt/codestra/operations/backup/check-backup-state.sh")' in text
    assert 'Path("/opt/codestra/backups/production-readiness-local")' in text
    assert 'f"CODESTRA_BACKUP_ROOT={READINESS_BACKUP_ROOT}"' in text
    assert '"evidence_integrity": "PASS"' in text
    assert 'expected_names = {f"codestra-{stamp}.tar.gz.gpg", "SHA256SUMS", "STATUS.txt"}' in text
    assert "codestra-backup.service" not in text
    assert "codestra-backup-state.service" not in text


def test_readiness_backup_validation_hashes_exact_evidence(monkeypatch, tmp_path) -> None:
    validator = tmp_path / "check-backup-state.sh"
    validator.write_text("#!/bin/sh\nexit 0\n")
    validator.chmod(0o755)
    root = tmp_path / "readiness"
    root.mkdir(mode=0o700)
    stamp = "20260822T161629Z"
    (root / "LAST_SUCCESS").write_text(stamp + "\n")
    (root / "LAST_SUCCESS").chmod(0o600)
    backup = root / stamp
    backup.mkdir(mode=0o700)
    names = [f"codestra-{stamp}.tar.gz.gpg", "SHA256SUMS", "STATUS.txt"]
    records = []
    for name in names:
        target = backup / name
        target.write_bytes(name.encode())
        target.chmod(0o600)
        records.append(f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {name}")
    evidence = backup / "EVIDENCE-SHA256SUMS"
    evidence.write_text("\n".join(records) + "\n")
    evidence.chmod(0o600)
    monkeypatch.setattr(OPERATOR, "BACKUP_STATE_VALIDATOR", validator)
    monkeypatch.setattr(OPERATOR, "READINESS_BACKUP_ROOT", root)
    monkeypatch.setattr(
        OPERATOR,
        "run_fixed",
        lambda _command: subprocess.CompletedProcess(_command, 0, ""),
    )
    assert OPERATOR.validate_backup_state()["evidence_integrity"] == "PASS"
    (backup / "STATUS.txt").write_bytes(b"corrupted")
    with pytest.raises(OPERATOR.OperatorError, match="checksum mismatch"):
        OPERATOR.validate_backup_state()


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
