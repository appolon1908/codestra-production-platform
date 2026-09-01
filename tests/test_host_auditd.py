from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "operations" / "host-auditd"


def load(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(PACKAGE / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


INSTALLER = load("host_auditd_installer", "install-provider-host-auditd.py")
VALIDATOR = load("host_auditd_validator", "validate-provider-host-auditd.py")


def test_managed_rules_are_additive_and_cover_operator_authorities() -> None:
    rules = (PACKAGE / "60-codestra-provider-host.rules").read_text()
    assert "\n-D" not in rules
    assert "\n-e 2" not in rules
    assert "-w /etc/ssh -p wa -k codestra_ssh_authority" in rules
    assert "-w /etc/sudoers.d -p wa -k codestra_sudo_authority" in rules
    assert "-w /home/codestra-admin -p wa -k codestra_operator_key" in rules
    assert "-w /opt/codestra -p wa -k codestra_operator_state" in rules
    assert "-w /var/lib/codestra -p wa -k codestra_operator_state" in rules
    assert "-F euid=0 -F auid=0 -k codestra_root_session_exec" in rules
    assert "-F euid=0 -F auid>=1000 -F auid!=unset -k codestra_privileged_exec" in rules
    assert VALIDATOR.REQUIRED_KEYS <= INSTALLER.managed_keys(rules)


def test_installer_never_installs_packages_or_touches_application_runtime() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    prohibited = (
        "apt-get install",
        "apt install",
        "docker",
        "compose",
        "iptables",
        "nft ",
        "ufw ",
        "sshd_config",
        "systemctl restart",
        "systemctl stop",
    )
    assert all(value not in source for value in prohibited)
    assert '[str(COMMANDS["service"]), "auditd", "stop"]' in source
    assert '"start", "auditd.service"' in source
    assert '"enable", "auditd.service"' in source


def test_installer_snapshots_before_managed_rule_mutation_and_records_after_validation() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    snapshot = source.index("snapshot_before(args.source_sha, before)")
    mutation = source.index("atomic_write(RULE_TARGET, rule_bytes, 0o600)", snapshot)
    validate = source.index("live = validate_live(rule_bytes)", mutation)
    evidence = source.index("atomic_write(INSTALLATION_RECORD, payload, 0o600)", validate)
    assert snapshot < mutation < validate < evidence
    assert set(INSTALLER.SNAPSHOT_NAMES) == {
        INSTALLER.RULE_TARGET,
        INSTALLER.AGGREGATE_TARGET,
        INSTALLER.VALIDATOR_TARGET,
        INSTALLER.INSTALLATION_RECORD,
    }


def test_audit_status_and_live_rule_key_parsers_fail_closed() -> None:
    status = VALIDATOR.audit_status(
        "enabled 1\npid 123\nlost 0\nbacklog 2\nbacklog_limit 8192\n"
    )
    assert status == {
        "enabled": 1,
        "pid": 123,
        "lost": 0,
        "backlog": 2,
        "backlog_limit": 8192,
    }
    with pytest.raises(VALIDATOR.ValidationError, match="incomplete"):
        VALIDATOR.audit_status("enabled 1\npid 123\nlost 0\n")
    assert VALIDATOR.rule_keys(
        "-w /etc/ssh -p wa -k codestra_ssh_authority\n"
        "-a always,exit -F arch=b64 -S execve -F key=codestra_privileged_exec\n"
    ) == {"codestra_ssh_authority", "codestra_privileged_exec"}


def test_rule_semantics_normalize_live_kernel_forms_without_accepting_drift() -> None:
    source = (
        "-a always,exit -F arch=b64 -S execve,execveat -F euid=0 "
        "-F auid>=1000 -F auid!=unset -k codestra_privileged_exec\n"
    )
    live = (
        "-a always,exit -F arch=c000003e -S execveat,execve -F euid=0 "
        "-F auid!=4294967295 -F auid>=1000 -F key=codestra_privileged_exec\n"
    )
    keys = {"codestra_privileged_exec"}
    assert INSTALLER.managed_rule_signatures(source, keys) == INSTALLER.managed_rule_signatures(live, keys)
    assert VALIDATOR.managed_rule_signatures(source, keys) == VALIDATOR.managed_rule_signatures(live, keys)
    drifted = live.replace("euid=0", "euid=1000")
    assert VALIDATOR.managed_rule_signatures(source, keys) != VALIDATOR.managed_rule_signatures(drifted, keys)


def test_atomic_install_completes_partial_regular_file_writes(tmp_path, monkeypatch) -> None:
    target = tmp_path / "managed.rules"
    real_write = os.write

    def short_write(descriptor: int, value) -> int:
        return real_write(descriptor, value[:3])

    monkeypatch.setattr(INSTALLER.os, "write", short_write)
    payload = b"0123456789abcdef\n"
    INSTALLER.atomic_write(target, payload, 0o600)
    assert target.read_bytes() == payload
    assert target.stat().st_mode & 0o777 == 0o600


def test_atomic_install_rejects_zero_length_short_write(tmp_path, monkeypatch) -> None:
    target = tmp_path / "managed.rules"
    monkeypatch.setattr(INSTALLER.os, "write", lambda descriptor, value: 0)
    with pytest.raises(INSTALLER.InstallError, match="short write"):
        INSTALLER.atomic_write(target, b"required\n", 0o600)
    assert not target.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_displaced_fifo_is_rejected_without_blocking(tmp_path) -> None:
    fifo = tmp_path / "managed.rules"
    os.mkfifo(fifo)
    with pytest.raises(INSTALLER.InstallError, match="non-regular"):
        INSTALLER.checked_regular(fifo)
    with pytest.raises(VALIDATOR.ValidationError, match="unsafe root-owned file"):
        VALIDATOR.checked_regular(fifo)


def test_validation_evidence_completes_partial_writes_before_readback(tmp_path, monkeypatch) -> None:
    target = tmp_path / "evidence.json"
    real_write = os.write

    def short_write(descriptor: int, value) -> int:
        return real_write(descriptor, value[:2])

    monkeypatch.setattr(VALIDATOR.os, "write", short_write)
    payload = b'{"result":"PASS"}\n'
    digest, size = VALIDATOR.durable_evidence(target, payload)
    assert target.read_bytes() == payload
    assert size == len(payload)
    assert len(digest) == 64


def test_validation_pass_is_emitted_only_after_durable_evidence() -> None:
    source = (PACKAGE / "validate-provider-host-auditd.py").read_text()
    durable = source.index("digest, size = durable_evidence(destination, payload)")
    result = source.index('"result": "PASS"', durable)
    output = source.index("print(json.dumps(", durable)
    assert durable < result < output
    assert "complete environment" not in source.lower()
    assert "os.environ" not in source
