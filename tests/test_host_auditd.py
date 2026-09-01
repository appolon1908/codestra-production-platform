from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

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


def signed_release_fixture(
    tmp_path: Path,
    *,
    source_sha: str = "a" * 40,
    installer_bytes: bytes | None = None,
    rule_bytes: bytes = b"-w /etc/ssh -p wa -k codestra_ssh_authority\n",
    validator_bytes: bytes = b"#!/usr/bin/python3\nprint('validator')\n",
) -> argparse.Namespace:
    key = tmp_path / "signing-key"
    subprocess.run(
        ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
    )
    public_fields = (tmp_path / "signing-key.pub").read_text().split()
    allowed_signers = tmp_path / "codestra-release.allowed_signers"
    allowed_signers.write_text(
        f"codestra-release {public_fields[0]} {public_fields[1]}\n"
    )
    allowed_signers.chmod(0o600)
    fingerprint = subprocess.run(
        ["/usr/bin/ssh-keygen", "-lf", str(key) + ".pub", "-E", "sha256"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[1]

    archive_name = f"codestra-production-platform-{source_sha}.tar.gz"
    archive = tmp_path / archive_name
    members = {
        INSTALLER.ARCHIVE_MEMBERS["installer"]: (
            (PACKAGE / "install-provider-host-auditd.py").read_bytes()
            if installer_bytes is None
            else installer_bytes
        ),
        INSTALLER.ARCHIVE_MEMBERS["rules"]: rule_bytes,
        INSTALLER.ARCHIVE_MEMBERS["validator"]: validator_bytes,
    }
    with tarfile.open(archive, "w:gz") as bundle:
        for name, value in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            info.mode = 0o600
            bundle.addfile(info, io.BytesIO(value))
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    deployment = tmp_path / "deployment-manifest.json"
    deployment.write_text(
        json.dumps(
            {
                "schema_version": "codestra.deployment.v1",
                "commit": source_sha,
                "artifact": archive_name,
                "artifact_sha256": archive_digest,
                "release_tuple": {
                    "orchestration_repository": (
                        "appolon1908-hue/codestra-production-platform"
                    ),
                    "orchestration_protected_sha": source_sha,
                },
            },
            sort_keys=True,
        )
        + "\n"
    )
    checksums = tmp_path / "manifest.sha256"
    checksums.write_text(
        f"{archive_digest}  {archive_name}\n"
        f"{hashlib.sha256(deployment.read_bytes()).hexdigest()}  deployment-manifest.json\n"
    )
    subprocess.run(
        [
            "/usr/bin/ssh-keygen",
            "-Y",
            "sign",
            "-q",
            "-f",
            str(key),
            "-n",
            "codestra-release",
            str(checksums),
        ],
        check=True,
    )
    return argparse.Namespace(
        source_sha=source_sha,
        change_id="CHG-TEST-001",
        approver="Security Owner",
        release_archive=str(archive),
        release_manifest=str(deployment),
        release_checksums=str(checksums),
        release_signature=str(checksums) + ".sig",
        allowed_signers=str(allowed_signers),
        expected_signer_fingerprint=fingerprint,
    )


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
    INSTALLER.require_additive_rules(rules.encode())
    with pytest.raises(INSTALLER.InstallError, match="global policy"):
        INSTALLER.require_additive_rules(b"  -D # hidden flush\n")
    with pytest.raises(INSTALLER.InstallError, match="global policy"):
        INSTALLER.require_additive_rules(b"-e 2\n")


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
    trust = source.index("rule_bytes, validator_bytes, release_binding = verify_signed_release(")
    snapshot = source.index("snapshot_before(args.source_sha, before)")
    mutation = source.index("atomic_write(RULE_TARGET, rule_bytes, 0o600)", snapshot)
    validate = source.index("live = validate_live(rule_bytes)", mutation)
    evidence = source.index("atomic_write(INSTALLATION_RECORD, payload, 0o600)", validate)
    assert trust < snapshot < mutation < validate < evidence
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


def test_installer_binds_installed_bytes_to_signed_protected_archive(tmp_path) -> None:
    expected_rule = b"-w /etc/audit -p wa -k exact_signed_rule\n"
    expected_validator = b"#!/usr/bin/python3\nprint('exact signed validator')\n"
    args = signed_release_fixture(
        tmp_path, rule_bytes=expected_rule, validator_bytes=expected_validator
    )
    stage, staged, digests = INSTALLER.snapshot_release_inputs(args)
    try:
        rule, validator, evidence = INSTALLER.verify_signed_release(
            args, stage, staged, digests
        )
    finally:
        INSTALLER.shutil.rmtree(stage)
    assert rule == expected_rule
    assert validator == expected_validator
    assert evidence["release_archive_sha256"] == digests["archive"]
    assert evidence["signer_fingerprint"] == args.expected_signer_fingerprint
    assert evidence["signature_verification"] == "PASS"


def test_checkout_installer_differing_from_signed_archive_is_rejected(tmp_path) -> None:
    args = signed_release_fixture(tmp_path, installer_bytes=b"#!/usr/bin/python3\n")
    stage, staged, digests = INSTALLER.snapshot_release_inputs(args)
    try:
        with pytest.raises(INSTALLER.InstallError, match="running installer differs"):
            INSTALLER.verify_signed_release(args, stage, staged, digests)
    finally:
        INSTALLER.shutil.rmtree(stage)


def test_release_input_fifo_is_rejected_nonblocking(tmp_path) -> None:
    args = argparse.Namespace(
        release_archive=str(tmp_path / "archive"),
        release_manifest=str(tmp_path / "deployment"),
        release_checksums=str(tmp_path / "checksums"),
        release_signature=str(tmp_path / "signature"),
        allowed_signers=str(tmp_path / "allowed_signers"),
    )
    os.mkfifo(args.release_archive)
    with pytest.raises(INSTALLER.InstallError, match="non-regular"):
        INSTALLER.snapshot_release_inputs(args)


def test_release_source_mismatch_fails_before_any_host_mutation(tmp_path, monkeypatch) -> None:
    args = signed_release_fixture(tmp_path)
    args.source_sha = "b" * 40
    mutations: list[Path] = []
    monkeypatch.setattr(
        INSTALLER,
        "secure_directory",
        lambda path, mode=0o700: mutations.append(path),
    )
    monkeypatch.setattr(INSTALLER, "require_prerequisites", lambda: None)
    with pytest.raises(INSTALLER.InstallError, match="release archive filename rejected"):
        INSTALLER.install(args)
    assert mutations == []


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
