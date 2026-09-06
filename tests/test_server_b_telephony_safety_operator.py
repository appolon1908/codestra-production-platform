from __future__ import annotations

import importlib.util
import ast
from importlib.machinery import SourceFileLoader
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "operations" / "server-b-telephony-safety"
OPERATOR = BASE / "codestra-server-b-telephony-safety"
INSTALLER = BASE / "install.sh"
ROLLBACK = BASE / "rollback.sh"
SUDOERS = BASE / "codestra-server-b-telephony-safety.sudoers"
AUTHORIZED_KEYS = BASE / "authorized_keys.template"


def load_operator():
    spec = importlib.util.spec_from_loader(
        "server_b_safety", SourceFileLoader("server_b_safety", str(OPERATOR))
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed(argv: list[str], stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(argv, returncode, stdout, "")


def invoke(monkeypatch, request: str | None, output: str):
    module = load_operator()
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["timeout"] == 10
        assert kwargs["env"]["PATH"] == "/usr/sbin:/usr/bin:/sbin:/bin"
        assert not kwargs.get("shell", False)
        return completed(argv, output)

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.sys, "argv", [str(OPERATOR)])
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    if request is None:
        monkeypatch.delenv("SSH_ORIGINAL_COMMAND", raising=False)
    else:
        monkeypatch.setenv("SSH_ORIGINAL_COMMAND", request)
    return module, module.main(), calls


def test_channels_matches_unchanged_consumer(monkeypatch, capsys):
    module, result, calls = invoke(
        monkeypatch,
        "/usr/bin/sudo -n /usr/sbin/asterisk -rx 'core show channels count'",
        "7 active channels\n3 active calls\n99 calls processed\n",
    )
    assert result == 0
    assert calls == [["/usr/sbin/asterisk", "-rx", "core show channels count"]]
    output = capsys.readouterr().out
    assert output == "7 active channels\n3 active calls\n99 calls processed\n"
    assert re.findall(r"(?m)^([0-9]+) active channels$", output) == ["7"]
    assert re.findall(r"(?m)^([0-9]+) active calls$", output) == ["3"]


def test_exact_requests_are_derived_from_unchanged_production_consumer():
    consumer_path = ROOT / "operations" / "production-operator" / "codestra-production-operator"
    tree = ast.parse(consumer_path.read_text())
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in {"VICIDIAL_CHANNELS_COMMAND", "VICIDIAL_REGISTRATIONS_COMMAND"}:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    module = load_operator()
    assert constants == {
        "VICIDIAL_CHANNELS_COMMAND": module.CHANNELS_REQUEST,
        "VICIDIAL_REGISTRATIONS_COMMAND": module.REGISTRATIONS_REQUEST,
    }
    assert set(constants.values()) == set(module.COMMANDS)


def test_registrations_matches_unchanged_consumer_native_output(monkeypatch, capsys):
    module, result, calls = invoke(
        monkeypatch,
        "/usr/bin/sudo -n /usr/sbin/asterisk -rx 'pjsip show registrations'",
        "<Registration/ServerURI..............................> <Auth..........> <Status.......>\n"
        "customer-sensitive-row\nObjects found: 2\n",
    )
    assert result == 0
    assert calls == [["/usr/sbin/asterisk", "-rx", "pjsip show registrations"]]
    assert capsys.readouterr().out == (
        "<Registration/ServerURI..............................> <Auth..........> <Status.......>\n"
        "customer-sensitive-row\nObjects found: 2\n"
    )


def test_no_registration_native_sentinel_is_preserved(monkeypatch, capsys):
    module, result, _ = invoke(monkeypatch, load_operator().REGISTRATIONS_REQUEST, "No objects found.\n")
    assert result == 0
    assert capsys.readouterr().out == "No objects found.\n"


@pytest.mark.parametrize(
    "original_command",
    [
        None,
        "",
        "core show channels count",
        "/usr/bin/sudo -n /usr/sbin/asterisk -rx core show channels count",
        "/usr/bin/sudo -n /usr/sbin/asterisk -rx 'core show channels count' extra",
        "/usr/bin/sudo -n /usr/sbin/asterisk -rx 'core show channels count'; id",
        "PATH=/tmp /usr/bin/sudo -n /usr/sbin/asterisk -rx 'core show channels count'",
        "/usr/bin/sudo -n /usr/sbin/asterisk -rx 'pjsip show registrations'\nwhoami",
        "/usr/local/sbin/codestra-vicidial-operator status",
        "/usr/local/sbin/codestra-vicidial-operator restore-test",
        "validate-backup latest",
        "/bin/sh",
    ],
)
def test_every_nonexact_request_is_rejected_without_execution(monkeypatch, original_command):
    _, result, calls = invoke(monkeypatch, original_command, "")
    assert result == 64
    assert calls == []


def test_non_root_and_argv_are_rejected(monkeypatch):
    module = load_operator()
    monkeypatch.setattr(module.os, "geteuid", lambda: 1001)
    assert module.main() == 64
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.sys, "argv", [str(OPERATOR), "extra"])
    assert module.main() == 64


def test_failed_asterisk_execution_fails_closed(monkeypatch, capsys):
    module = load_operator()
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.sys, "argv", [str(OPERATOR)])
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", module.CHANNELS_REQUEST)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda argv, **kwargs: completed(argv, "sensitive failure", returncode=1),
    )
    assert module.main() == 1
    assert capsys.readouterr().out == ""


def test_policy_templates_are_narrow():
    sudoers = SUDOERS.read_text()
    auth = AUTHORIZED_KEYS.read_text()
    assert "NOPASSWD: ALL" not in sudoers
    assert "/usr/sbin/asterisk" not in sudoers
    assert "codestra-vicidial-operator" not in sudoers
    assert "*" not in sudoers
    assert "noexec" not in sudoers  # The wrapper must exec its one fixed Asterisk child.
    assert "!setenv" in sudoers
    assert 'env_keep += "SSH_ORIGINAL_COMMAND"' in sudoers
    assert sudoers.count("env_keep") == 1
    assert not re.search(r'env_keep[^\n]*\b(PATH|HOME|USER|SHELL|PYTHONPATH)\b', sudoers)
    assert "command=\"/usr/bin/sudo -n /usr/local/sbin/codestra-server-b-telephony-safety\"" in auth
    for restriction in ("restrict", "no-agent-forwarding", "no-port-forwarding", "no-X11-forwarding", "no-pty"):
        assert restriction in auth
    assert "SSH_PUBLIC_KEY_PLACEHOLDER" in auth


def test_no_legacy_delegation_or_mutating_primitives():
    text = OPERATOR.read_text()
    forbidden = (
        "CORE_OPERATOR",
        "LEGACY_ACTIONS",
        "os.exec",
        "shell=True",
        "restore-test",
        "docker",
        "systemctl",
        "mysql",
        "psql",
        "createdb",
        "symlink",
        "unlink",
    )
    for token in forbidden:
        assert token not in text
    assert list(load_operator().COMMANDS.values()) == [
        ["/usr/sbin/asterisk", "-rx", "core show channels count"],
        ["/usr/sbin/asterisk", "-rx", "pjsip show registrations"],
    ]


def test_installer_and_rollback_contracts_are_fail_closed():
    installer = INSTALLER.read_text()
    rollback = ROLLBACK.read_text()
    for required in (
        "[[ $EUID -eq 0 && $# -eq 1 ]]",
        "status --porcelain",
        "REVISION_MISMATCH",
        "merge-base --is-ancestor",
        "origin/release/production-activation",
        "python3 -m py_compile",
        "visudo -cf",
        "sshd -t",
        "sha256sum -c /etc/codestra/server-b-telephony-safety/SHA256SUMS",
        "INSTALLED_REVISION_MISMATCH",
        "flock -n \"$installer_lock\" || die INSTALLER_ALREADY_RUNNING",
        "lock_root=$lock_parent/.locks",
        "set -o noclobber",
        "exec {installer_lock}<>",
        "mktemp -d /root/codestra-server-b-telephony-safety-backup-XXXXXXXXXXXX",
        "BACKUP_FORMAT=server-b-telephony-safety-v2",
        "BACKUP-SHA256SUMS",
        "mv -f",
    ):
        assert required in installer
    assert "restore-test" not in installer
    assert "visudo -cf /etc/sudoers" in rollback
    assert "sshd -t" in rollback
    assert re.search(r"backup=\$1", rollback)
    assert "[A-Za-z0-9]{12}" in rollback
    assert "INCOMPLETE_BACKUP" in rollback
    assert "BACKUP_CHECKSUM_MISMATCH" in rollback
    assert "/run/lock" not in installer
    assert "/run/lock" not in rollback
    assert "/root/vicidial-sync-remediation" in installer
    assert "/root/vicidial-sync-remediation" in rollback
    assert "set -o noclobber" in rollback


def test_lock_is_exclusive_and_precedes_all_backup_or_staging_resources(tmp_path):
    installer = INSTALLER.read_text()
    lock = installer.index('flock -n "$installer_lock"')
    assert lock < installer.index("backup=$(mktemp -d")
    assert lock < installer.index("stage=$(mktemp -d")

    lock_path = tmp_path / "installer.lock"
    marker = tmp_path / "backup-created"
    holder = subprocess.Popen(
        ["flock", str(lock_path), "sh", "-c", "printf ready; sleep 5"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout and holder.stdout.read(5) == "ready"
    contender = subprocess.run(
        ["flock", "-n", str(lock_path), "sh", "-c", f"touch {marker}"],
        check=False,
    )
    holder.terminate()
    holder.wait(timeout=2)
    assert contender.returncode != 0
    assert not marker.exists()


def test_randomized_backup_and_temporary_targets_cannot_collide(tmp_path):
    created = []
    for _ in range(32):
        result = subprocess.run(
            ["mktemp", "-d", str(tmp_path / "codestra-server-b-telephony-safety-backup-XXXXXXXXXXXX")],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        created.append(Path(result.stdout.strip()))
    assert len(set(created)) == 32
    assert all(re.fullmatch(r"codestra-server-b-telephony-safety-backup-[A-Za-z0-9]{12}", path.name) for path in created)

    installer = INSTALLER.read_text()
    assert ".new" not in installer
    assert installer.count("XXXXXXXXXXXX)") >= 6


def test_completed_backup_seal_is_written_before_staging_and_required_by_rollback():
    installer = INSTALLER.read_text()
    rollback = ROLLBACK.read_text()
    assert installer.index('>"$backup/COMPLETE"') < installer.index("stage=$(mktemp -d")
    assert installer.index('>BACKUP-SHA256SUMS') < installer.index('>"$backup/COMPLETE"')
    assert rollback.index("INCOMPLETE_BACKUP") < rollback.index("while IFS=")
    assert rollback.index("BACKUP_CHECKSUM_MISMATCH") < rollback.index("while IFS=")


def test_evidence_template_is_machine_readable_and_locally_derived():
    evidence = json.loads((BASE / "evidence.json").read_text())
    assert re.fullmatch(r"[0-9a-f]{64}", evidence["assessment_sha256"])
    assert evidence["assessment_sha256_source"] == "locally-computed"
    assert evidence["ssh_public_key_fingerprint_source"] == "local-assessment-and-independent-key-derivation"
    assert evidence["production_changed"] is False
