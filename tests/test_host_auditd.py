from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace

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
    fingerprint_authority = tmp_path / "allowed_signers.ssh-fingerprint"
    fingerprint_authority.write_text(fingerprint + "\n")
    fingerprint_authority.chmod(0o600)

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
        trust_allowed_signers=allowed_signers,
        trust_fingerprint=fingerprint_authority,
        signer_fingerprint=fingerprint,
    )


def bind_test_trust(args: argparse.Namespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(INSTALLER, "ALLOWED_SIGNERS_AUTHORITY", args.trust_allowed_signers)
    monkeypatch.setattr(
        INSTALLER, "SIGNER_FINGERPRINT_AUTHORITY", args.trust_fingerprint
    )


def test_managed_rules_are_additive_and_cover_operator_authorities() -> None:
    rules = (PACKAGE / "60-codestra-provider-host.rules").read_text()
    assert "\n-D" not in rules
    assert "\n-e 2" not in rules
    assert "-w /etc/ssh -p wa -k codestra_ssh_authority" in rules
    assert "-w /etc/sudoers.d -p wa -k codestra_sudo_authority" in rules
    assert "-w /etc/codestra/release -p wa -k codestra_release_trust" in rules
    assert "-w /home/codestra-admin -p wa -k codestra_operator_key" in rules
    assert "-w /opt/codestra -p wa -k codestra_operator_state" in rules
    assert "-w /var/lib/codestra -p wa -k codestra_operator_state" in rules
    assert "-F euid=0 -F auid=0 -k codestra_root_session_exec" in rules
    assert "-F euid=0 -F auid>=1000 -F auid!=unset -k codestra_privileged_exec" in rules
    assert "-F euid=0 -F auid>=1 -F auid<1000 -k codestra_service_privileged_exec" in rules
    assert "-F euid=0 -F auid=4294967295 -k codestra_unset_privileged_exec" in rules
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
    launcher = source.index("launcher_bytes = validator_launcher_bytes", trust)
    snapshot = source.index("snapshot_before(args.source_sha, before)")
    mutation = source.index("atomic_write(RULE_TARGET, rule_bytes, 0o600)", snapshot)
    validator_mutation = source.index(
        "atomic_write(VALIDATOR_TARGET, validator_bytes, 0o750)", mutation
    )
    launcher_mutation = source.index(
        "atomic_write(VALIDATOR_LAUNCHER_TARGET, launcher_bytes, 0o750)",
        validator_mutation,
    )
    readback = source.index(
        "installed_payloads(rule_bytes, validator_bytes, launcher_bytes)",
        launcher_mutation,
    )
    service_mutation = source.index(
        'run_checked([str(COMMANDS["systemctl"]), "enable", "auditd.service"])',
        readback,
    )
    validate = source.index(
        "live = validate_live(rule_bytes, validator_bytes, launcher_bytes)",
        service_mutation,
    )
    evidence = source.index("return persist_installation_record(record)", validate)
    assert (
        trust
        < launcher
        < snapshot
        < mutation
        < validator_mutation
        < launcher_mutation
        < readback
        < service_mutation
        < validate
        < evidence
    )
    assert set(INSTALLER.SNAPSHOT_NAMES) == {
        INSTALLER.RULE_TARGET,
        INSTALLER.AGGREGATE_TARGET,
        INSTALLER.VALIDATOR_TARGET,
        INSTALLER.VALIDATOR_LAUNCHER_TARGET,
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
    unset_source = (
        "-a always,exit -F arch=b64 -S execve,execveat -F euid=0 "
        "-F auid=4294967295 -k codestra_unset_privileged_exec\n"
    )
    unset_live = unset_source.replace("auid=4294967295", "auid=unset")
    unset_keys = {"codestra_unset_privileged_exec"}
    assert INSTALLER.managed_rule_signatures(
        unset_source, unset_keys
    ) == INSTALLER.managed_rule_signatures(unset_live, unset_keys)
    assert VALIDATOR.managed_rule_signatures(
        unset_source, unset_keys
    ) == VALIDATOR.managed_rule_signatures(unset_live, unset_keys)


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


def test_installer_binds_installed_bytes_to_signed_protected_archive(
    tmp_path, monkeypatch
) -> None:
    expected_rule = b"-w /etc/audit -p wa -k exact_signed_rule\n"
    expected_validator = b"#!/usr/bin/python3\nprint('exact signed validator')\n"
    args = signed_release_fixture(
        tmp_path, rule_bytes=expected_rule, validator_bytes=expected_validator
    )
    bind_test_trust(args, monkeypatch)
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
    assert evidence["signer_fingerprint"] == args.signer_fingerprint
    assert evidence["signature_verification"] == "PASS"


def test_checkout_installer_differing_from_signed_archive_is_rejected(
    tmp_path, monkeypatch
) -> None:
    args = signed_release_fixture(tmp_path, installer_bytes=b"#!/usr/bin/python3\n")
    bind_test_trust(args, monkeypatch)
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
    bind_test_trust(args, monkeypatch)
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


def test_signer_authority_is_fixed_outside_installer_arguments() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    assert 'Path("/etc/codestra/release")' in source
    assert 'RELEASE_TRUST_ROOT / "allowed_signers"' in source
    assert 'RELEASE_TRUST_ROOT / "allowed_signers.ssh-fingerprint"' in source
    assert 'add_argument("--allowed-signers"' not in source
    assert 'add_argument("--expected-signer-fingerprint"' not in source
    assert "Path(args.allowed_signers)" not in source
    assert "args.expected_signer_fingerprint" not in source


def test_installed_validator_is_read_back_before_service_mutation(
    tmp_path, monkeypatch
) -> None:
    rule_target = tmp_path / "managed.rules"
    validator_target = tmp_path / "validator"
    launcher_target = tmp_path / "launcher"
    rule_target.write_bytes(b"signed rule\n")
    validator_target.write_bytes(b"displaced validator\n")
    launcher_target.write_bytes(b"launcher\n")
    rule_target.chmod(0o600)
    validator_target.chmod(0o750)
    launcher_target.chmod(0o750)
    monkeypatch.setattr(INSTALLER, "RULE_TARGET", rule_target)
    monkeypatch.setattr(INSTALLER, "VALIDATOR_TARGET", validator_target)
    monkeypatch.setattr(INSTALLER, "VALIDATOR_LAUNCHER_TARGET", launcher_target)
    with pytest.raises(INSTALLER.InstallError, match="validator differs"):
        INSTALLER.installed_payloads(
            b"signed rule\n", b"signed validator\n", b"launcher\n"
        )


def test_installed_payloads_require_exact_executable_metadata(
    tmp_path, monkeypatch
) -> None:
    rule_target = tmp_path / "managed.rules"
    validator_target = tmp_path / "validator"
    launcher_target = tmp_path / "launcher"
    rule_target.write_bytes(b"signed rule\n")
    validator_target.write_bytes(b"signed validator\n")
    launcher_target.write_bytes(b"signed launcher\n")
    rule_target.chmod(0o600)
    validator_target.chmod(0o750)
    launcher_target.chmod(0o750)
    monkeypatch.setattr(INSTALLER, "RULE_TARGET", rule_target)
    monkeypatch.setattr(INSTALLER, "VALIDATOR_TARGET", validator_target)
    monkeypatch.setattr(INSTALLER, "VALIDATOR_LAUNCHER_TARGET", launcher_target)

    INSTALLER.installed_payloads(
        b"signed rule\n", b"signed validator\n", b"signed launcher\n"
    )
    launcher_target.chmod(0o600)
    with pytest.raises(INSTALLER.InstallError, match="exact root metadata"):
        INSTALLER.installed_payloads(
            b"signed rule\n", b"signed validator\n", b"signed launcher\n"
        )


@pytest.mark.parametrize("metadata_case", [
    None, ("change_id", ""), ("approver", " "), ("installed_at_utc", "yesterday"),
    ("installed_at_utc", "2026-09-07T13:00:00"), ("installed_at_utc", "2026-09-07T13:00:00-04:00"),
    ("rollback_stamp", 7), ("release.release_archive", None),
    ("release.signer_fingerprint", "invalid"), ("release.release_archive_sha256", int("1" * 64)),
    ("state.kernel_enabled", True), ("state.kernel_enabled", 1.0), ("state.kernel_enabled", "1"),
    ("state.kernel_lost", False), ("state.kernel_lost", 0.0), ("state.kernel_lost", "0"),
    ("state.managed_keys", []), ("state.managed_keys", "codestra_audit_authority"),
    ("state.managed_keys", [True]), ("state.managed_keys", ["unknown"]),
])
def test_validation_pass_is_bound_to_installed_validator_bytes(monkeypatch, metadata_case) -> None:
    rule_path = Path("/test/managed.rules")
    validator_path = Path("/test/validator")
    launcher_path = Path("/test/launcher")
    record_path = Path("/test/installation.json")
    source_sha = "a" * 40
    rule = b"signed rule\n"
    validator = b"signed validator\n"
    launcher = b"signed launcher\n"
    stamp = "20260901T120000Z"
    backup_root = Path("/test/backups")
    rollback_path = backup_root / stamp / "rollback.json"
    checksum_path = backup_root / stamp / "SHA256SUMS"
    rollback = json.dumps({"schema": "codestra.host-auditd.rollback.v1",
                           "stamp": stamp, "source_sha": source_sha,
                           "service_before": {"enabled": True, "active": True},
                           "files": []}, sort_keys=True).encode()
    digest = "b" * 64
    record = json.dumps(
        {
            "schema": "codestra.host-auditd.installation.v1",
            "source_sha": source_sha,
            "change_id": "CHG-TEST-001", "approver": "Security Owner",
            "installed_at_utc": "2026-09-01T12:00:00Z", "rollback_stamp": stamp,
            "rule_sha256": hashlib.sha256(rule).hexdigest(),
            "validator_sha256": hashlib.sha256(validator).hexdigest(),
            "validator_launcher_sha256": hashlib.sha256(launcher).hexdigest(),
            "release": {"release_archive": "release.tar.gz",
                        "release_archive_sha256": digest, "release_manifest_sha256": digest,
                        "release_checksums_sha256": digest, "release_signature_sha256": digest,
                        "allowed_signers_sha256": digest,
                        "signer_fingerprint_authority_sha256": digest,
                        "signer_fingerprint": "SHA256:" + "A" * 43,
                        "signature_verification": "PASS"},
            "state": {"service": "enabled-active", "kernel_enabled": 1,
                      "kernel_lost": 0, "managed_rule_sha256": hashlib.sha256(rule).hexdigest(),
                      "validator_sha256": hashlib.sha256(validator).hexdigest(),
                      "validator_launcher_sha256": hashlib.sha256(launcher).hexdigest(),
                      "managed_keys": sorted(VALIDATOR.REQUIRED_KEYS)},
        }
    ).encode()
    payloads = {
        rule_path: rule,
        validator_path: validator,
        launcher_path: launcher,
        record_path: record,
        rollback_path: rollback,
        checksum_path: f"{hashlib.sha256(rollback).hexdigest()}  rollback.json\n".encode(),
    }
    monkeypatch.setattr(VALIDATOR, "RULE_TARGET", rule_path)
    monkeypatch.setattr(VALIDATOR, "VALIDATOR_TARGET", validator_path)
    monkeypatch.setattr(VALIDATOR, "VALIDATOR_LAUNCHER", launcher_path)
    monkeypatch.setattr(VALIDATOR, "INSTALLATION_RECORD", record_path)
    monkeypatch.setattr(VALIDATOR, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(
        VALIDATOR,
        "checked_regular",
        lambda path, max_bytes=1024 * 1024: payloads[path],
    )

    if metadata_case is not None:
        key, value = metadata_case
        altered = json.loads(record)
        parts = key.split(".")
        target = altered
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
        payloads[record_path] = json.dumps(altered).encode()
        with pytest.raises(VALIDATOR.ValidationError):
            VALIDATOR.installed_release_binding(source_sha)
        return

    assert VALIDATOR.installed_release_binding(source_sha) == (
        rule,
        hashlib.sha256(rule).hexdigest(),
        hashlib.sha256(validator).hexdigest(),
        hashlib.sha256(launcher).hexdigest(),
    )
    payloads[validator_path] = b"valid Python but displaced validator\n"
    with pytest.raises(VALIDATOR.ValidationError, match="validator binding"):
        VALIDATOR.installed_release_binding(source_sha)


def test_root_only_launcher_verifies_target_before_executing_it(tmp_path: Path) -> None:
    try:
        pwd.getpwnam("codestra-admin")
    except KeyError:
        pytest.skip("codestra-admin unavailable for host-identity execution test")
    source_sha = "a" * 40
    validator = tmp_path / "validator"
    launcher = tmp_path / "launcher"
    validator_bytes = (
        b"import sys\n"
        b"print('VALIDATOR_EXECUTED ' + ' '.join(sys.argv[1:]))\n"
    )
    validator.write_bytes(validator_bytes)
    validator.chmod(0o750)
    launcher.write_bytes(
        INSTALLER.validator_launcher_bytes(
            validator_bytes,
            source_sha,
            validator_target=validator,
            authority_root=tmp_path,
        )
    )
    launcher.chmod(0o750)
    completed = subprocess.run(
        [str(launcher), "--expected-source-sha", source_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    assert f"--expected-source-sha {source_sha}" in completed.stdout
    validator.write_bytes(b"print('displaced')\n")
    rejected = subprocess.run(
        [str(launcher), "--expected-source-sha", source_sha],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "HOST_AUDITD_LAUNCH=FAIL" in rejected.stderr


def test_validator_operator_check_includes_executable_and_parent_authority() -> None:
    source = (PACKAGE / "validate-provider-host-auditd.py").read_text()
    writability_check = source.split("if not operator_cannot_modify(", 1)[1]
    for token in (
        "VALIDATOR_TARGET.parent",
        "VALIDATOR_TARGET",
        "VALIDATOR_LAUNCHER.parent",
        "VALIDATOR_LAUNCHER",
    ):
        assert token in writability_check
    expected = {
        Path("/"),
        Path("/usr"),
        Path("/usr/local"),
        Path("/usr/local/sbin"),
        INSTALLER.VALIDATOR_TARGET,
        INSTALLER.VALIDATOR_LAUNCHER_TARGET,
    }
    assert expected <= set(
        INSTALLER.path_authority_chain(
            [INSTALLER.VALIDATOR_TARGET, INSTALLER.VALIDATOR_LAUNCHER_TARGET]
        )
    )
    assert expected <= set(
        VALIDATOR.path_authority_chain(
            [VALIDATOR.VALIDATOR_TARGET, VALIDATOR.VALIDATOR_LAUNCHER]
        )
    )
    launcher_source = INSTALLER.validator_launcher_bytes(
        b"validator\n", "a" * 40
    ).decode()
    assert "authority_chain(launcher, AUTHORITY_ROOT)" in launcher_source
    assert "authority_chain(VALIDATOR, AUTHORITY_ROOT)" in launcher_source
    assert "while cursor != root" in launcher_source


def test_release_trust_and_python_runtime_are_in_operator_acl_boundary() -> None:
    installer = (PACKAGE / "install-provider-host-auditd.py").read_text()
    prerequisite = installer.split("def require_prerequisites()", 1)[1].split(
        "def snapshot_file", 1
    )[0]
    for token in (
        "ALLOWED_SIGNERS_AUTHORITY",
        "SIGNER_FINGERPRINT_AUTHORITY",
        "PYTHON_INTERPRETER.parent",
        "python_target",
        "*COMMANDS.values()",
        "*command_targets",
        "path_authority_chain",
        "operator_cannot_modify",
    ):
        assert token in prerequisite
    validator = (PACKAGE / "validate-provider-host-auditd.py").read_text()
    validation = validator.split("def validate(expected_source_sha", 1)[1]
    for token in (
        "ALLOWED_SIGNERS_AUTHORITY",
        "SIGNER_FINGERPRINT_AUTHORITY",
        "PYTHON_INTERPRETER.parent",
        "python_target",
        "*COMMANDS.values()",
        "*command_targets",
    ):
        assert token in validation


def test_command_helpers_are_root_owned_digested_and_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = tmp_path / "audit-helper"
    helper.write_bytes(b"#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)

    monkeypatch.setattr(INSTALLER, "COMMANDS", {"helper": helper})
    installer_identities = INSTALLER.command_runtime_identities()
    assert installer_identities == {
        "helper": (helper, hashlib.sha256(helper.read_bytes()).hexdigest())
    }

    monkeypatch.setattr(VALIDATOR, "COMMANDS", {"helper": helper})
    validator_identities = VALIDATOR.command_runtime_identities()
    assert validator_identities == installer_identities

    helper.chmod(0o775)
    with pytest.raises(INSTALLER.InstallError, match="authority rejected"):
        INSTALLER.command_runtime_identities()
    with pytest.raises(VALIDATOR.ValidationError, match="authority rejected"):
        VALIDATOR.command_runtime_identities()


def test_command_acl_boundary_precedes_first_privileged_helper_execution() -> None:
    installer = (PACKAGE / "install-provider-host-auditd.py").read_text()
    prerequisite = installer.split("def require_prerequisites()", 1)[1].split(
        "def snapshot_file", 1
    )[0]
    installer_acl = prerequisite.index(
        'raise InstallError("codestra-admin can modify audit command authority")'
    )
    first_installer_command = prerequisite.index("package = command_output(")
    assert installer_acl < first_installer_command

    validator = (PACKAGE / "validate-provider-host-auditd.py").read_text()
    validation = validator.split("def validate(expected_source_sha", 1)[1].split(
        "def main", 1
    )[0]
    validator_acl = validation.index(
        'raise ValidationError("codestra-admin can modify audit authority")'
    )
    first_validator_command = validation.index("active = run(")
    assert validator_acl < first_validator_command


def test_validator_rechecks_kernel_health_after_synthetic_readback() -> None:
    source = (PACKAGE / "validate-provider-host-auditd.py").read_text()
    validation = source.split("def validate(expected_source_sha", 1)[1].split(
        "def main", 1
    )[0]
    first_status = validation.index("healthy_audit_status()")
    readback = validation.index("if not found:")
    final_status = validation.index("final_status = healthy_audit_status()")
    evidence = validation.index('"lost_records": final_status["lost"]')
    assert first_status < readback < final_status < evidence


def test_healthy_audit_status_fails_closed_on_post_probe_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = "enabled 1\npid 42\nlost 1\nbacklog 0\nbacklog_limit 8192\n"
    monkeypatch.setattr(VALIDATOR, "run", lambda command: status)
    with pytest.raises(VALIDATOR.ValidationError, match="kernel state"):
        VALIDATOR.healthy_audit_status()


def test_operator_writability_probe_detects_extended_acl() -> None:
    if shutil.which("setfacl") is None:
        pytest.skip("setfacl unavailable")
    try:
        pwd.getpwnam("codestra-admin")
    except KeyError:
        pytest.skip("codestra-admin unavailable")
    with tempfile.TemporaryDirectory(prefix="codestra-acl-test.", dir="/tmp") as directory:
        root = Path(directory)
        root.chmod(0o711)
        authority = root / "authority"
        authority.write_text("public trust authority\n")
        authority.chmod(0o600)
        assert INSTALLER.operator_cannot_modify([root, authority])
        subprocess.run(
            ["setfacl", "-m", "u:codestra-admin:rw", str(authority)], check=True
        )
        assert not INSTALLER.operator_cannot_modify([root, authority])


def test_launcher_uses_isolated_bound_python_runtime() -> None:
    launcher = INSTALLER.validator_launcher_bytes(
        b"print('validator')\n", "a" * 40
    ).decode()
    assert launcher.startswith("#!/usr/bin/python3 -I\n")
    for token in (
        'Path("/proc/self/exe").resolve(strict=True)',
        "PYTHON_ALIAS.resolve(strict=True) != PYTHON_TARGET",
        "EXPECTED_PYTHON_SHA256",
        "exact_digest(PYTHON_TARGET, MAX_PYTHON_BYTES)",
        "identity_can_write(authority)",
        "os.execve(\n        str(PYTHON_TARGET)",
    ):
        assert token in launcher


def test_installation_record_is_read_back_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "installation.json"
    monkeypatch.setattr(INSTALLER, "INSTALLATION_RECORD", target)
    record = {"schema": "codestra.host-auditd.installation.v1", "source_sha": "a" * 40}
    assert INSTALLER.persist_installation_record(record) == record

    def corrupt_write(path: Path, _value: bytes, mode: int) -> None:
        path.write_bytes(b"{}\n")
        path.chmod(mode)

    monkeypatch.setattr(INSTALLER, "atomic_write", corrupt_write)
    with pytest.raises(INSTALLER.InstallError, match="read-back differs"):
        INSTALLER.persist_installation_record(record)


def test_exact_root_record_metadata_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"{}\n"

    def metadata(mode: int, uid: int = 0, gid: int = 0):
        return SimpleNamespace(st_mode=stat.S_IFREG | mode, st_uid=uid, st_gid=gid)

    monkeypatch.setattr(
        INSTALLER,
        "checked_regular_snapshot",
        lambda path, max_bytes=1024 * 1024: (payload, metadata(0o600)),
    )
    assert INSTALLER.checked_root_regular_exact(Path("/record"), 0o600) == payload
    for info in (metadata(0o644), metadata(0o600, uid=1000), metadata(0o600, gid=1000)):
        monkeypatch.setattr(
            INSTALLER,
            "checked_regular_snapshot",
            lambda path, max_bytes=1024 * 1024, info=info: (payload, info),
        )
        with pytest.raises(INSTALLER.InstallError, match="exact root metadata"):
            INSTALLER.checked_root_regular_exact(Path("/record"), 0o600)


def test_idempotent_install_requires_complete_canonical_record() -> None:
    args = argparse.Namespace(
        source_sha="a" * 40,
        change_id="CHG-TEST-001",
        approver="Security Owner",
    )
    release = {"release_archive_sha256": "b" * 64}
    live = {
        "service": "enabled-active",
        "kernel_enabled": 1,
        "kernel_lost": 0,
        "managed_rule_sha256": "c" * 64,
        "validator_sha256": "d" * 64,
        "validator_launcher_sha256": "e" * 64,
        "managed_keys": sorted(VALIDATOR.REQUIRED_KEYS),
    }
    record = {
        "schema": "codestra.host-auditd.installation.v1",
        "source_sha": args.source_sha,
        "change_id": args.change_id,
        "approver": args.approver,
        "installed_at_utc": "2026-09-01T12:00:00Z",
        "rollback_stamp": "20260901T120000Z",
        "rule_sha256": live["managed_rule_sha256"],
        "validator_sha256": live["validator_sha256"],
        "validator_launcher_sha256": live["validator_launcher_sha256"],
        "release": release,
        "state": live,
    }
    assert INSTALLER.validate_installation_record(record, args, release, live) == record
    corruptions = {
        "schema": "wrong",
        "source_sha": "f" * 40,
        "change_id": "CHG-OTHER",
        "approver": "Other Owner",
        "installed_at_utc": "not-a-time",
        "rollback_stamp": "not-a-stamp",
        "rule_sha256": "0" * 64,
        "validator_sha256": "0" * 64,
        "validator_launcher_sha256": "0" * 64,
        "release": {},
        "state": {},
    }
    for field, value in corruptions.items():
        changed = dict(record)
        changed[field] = value
        with pytest.raises(INSTALLER.InstallError, match="installation record"):
            INSTALLER.validate_installation_record(changed, args, release, live)
    missing = dict(record)
    missing.pop("validator_sha256")
    with pytest.raises(INSTALLER.InstallError, match="schema"):
        INSTALLER.validate_installation_record(missing, args, release, live)


def test_install_and_rollback_hold_one_host_wide_mutation_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeLock:
        def __enter__(self):
            events.append("locked")

        def __exit__(self, *args):
            events.append("unlocked")

    monkeypatch.setattr(INSTALLER, "mutation_lock", FakeLock)
    monkeypatch.setattr(
        INSTALLER, "_install_locked", lambda args: events.append("install") or {}
    )
    monkeypatch.setattr(
        INSTALLER, "_rollback_locked", lambda args: events.append("rollback") or {}
    )
    INSTALLER.install(argparse.Namespace())
    INSTALLER.rollback(argparse.Namespace())
    assert events == [
        "locked",
        "install",
        "unlocked",
        "locked",
        "rollback",
        "unlocked",
    ]


def test_idempotent_install_authenticates_recorded_checkpoint() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    idempotent = source.index("validated = validate_installation_record(")
    authenticate = source.index("validate_rollback_checkpoint(", idempotent)
    returned = source.index("return validated", authenticate)
    assert idempotent < authenticate < returned


def test_exact_aggregate_checkpoint_is_restored_after_augenrules_load() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    restore = source.index("def restore_checkpoint(")
    load = source.index('run_checked([str(COMMANDS["augenrules"]), "--load"])', restore)
    restore_aggregate = source.index("restore_file(aggregate_record, checkpoint)", load)
    assert restore < load < restore_aggregate
    assert 'aggregate_record.get("present") is False' not in source[load:restore_aggregate]


def test_rollback_fsyncs_parent_after_deleting_absent_target() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    unlink = source.index("target.unlink()", source.index("def restore_file("))
    sync = source.index("fsync_directory(target.parent)", unlink)
    assert unlink < sync


def test_verified_bootstrap_checks_stdlib_before_python_execution() -> None:
    launcher = (PACKAGE / "install-provider-host-auditd-verified").read_text()
    assert "/usr/bin/find" in launcher
    assert "! -user root -o -perm /022" in launcher
    assert launcher.index("/usr/bin/find") < launcher.index('exec "$python_image" -I')
    assert "/usr/local/sbin/install-provider-host-auditd-verified" in launcher
    assert "/usr/local/libexec/codestra-host-auditd/install-provider-host-auditd.py" in launcher
    assert 'exec "$python_image" -I -S' in launcher
    assert "python3.sha256" in launcher
    assert "/usr/bin/getfacl -cp" in launcher
    assert "python3.stdlib" in launcher
    assert "/usr/bin/getfacl -Rcp" in launcher
    assert "/usr/bin/lsattr -d" in launcher
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    assert "verified bootstrap launcher is required" in source


def test_root_bootstrap_installs_launcher_outside_operator_checkout() -> None:
    bootstrap = (PACKAGE / "bootstrap-provider-host-auditd-launcher").read_text()
    assert 'test "$EUID" -eq 0' in bootstrap
    assert "/usr/local/sbin/install-provider-host-auditd-verified" in bootstrap
    assert "/usr/local/libexec/codestra-host-auditd/install-provider-host-auditd.py" in bootstrap
    assert "python3.sha256" in bootstrap
    assert "python3.stdlib" in bootstrap
    assert "/usr/bin/chattr +i" in bootstrap
    assert "source_sha=%s" in bootstrap
    assert "/usr/bin/cmp -s" in bootstrap
    assert "/var/lib/codestra/host-auditd-bootstrap" in bootstrap
    assert bootstrap.index("/usr/bin/cmp -s") < bootstrap.index(
        "CODESTRA_HOST_AUDITD_LAUNCHER_BOOTSTRAP=PASS"
    )


def test_validation_holds_the_installation_lock_through_evidence() -> None:
    source = (PACKAGE / "validate-provider-host-auditd.py").read_text()
    acquire = source.index("fcntl.flock(lock_fd, fcntl.LOCK_EX)")
    persist = source.index("durable_evidence(destination, payload)", acquire)
    release = source.index("fcntl.flock(lock_fd, fcntl.LOCK_UN)", persist)
    assert acquire < persist < release


def test_restored_ownership_is_fsynced_before_rollback_evidence() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    restore = source.split("def restore_file(", 1)[1].split(
        "def restored_checkpoint_evidence", 1
    )[0]
    assert restore.index("os.chown(") < restore.index("fsync_file(target)")


def test_validator_requires_exact_root_owned_release_trust() -> None:
    source = (PACKAGE / "validate-provider-host-auditd.py").read_text()
    trust = source.index("def require_root_release_trust()")
    validation = source.index("def validate(expected_source_sha", trust)
    assert "info.st_uid != 0" in source[trust:validation]
    assert "info.st_gid != 0" in source[trust:validation]
    assert "stat.S_IMODE(info.st_mode) != expected_mode" in source[trust:validation]
    assert "require_root_release_trust()" in source[validation:]


def test_rollback_revalidates_restored_files_and_service_before_completion(
    tmp_path,
) -> None:
    target = tmp_path / "managed.rules"
    absent = tmp_path / "previously-absent"
    expected = b"checkpoint bytes\n"
    target.write_bytes(expected)
    target.chmod(0o640)
    info = target.stat()
    record = {
        "files": [
            {
                "path": str(target),
                "present": True,
                "sha256": hashlib.sha256(expected).hexdigest(),
                "mode": 0o640,
                "uid": info.st_uid,
                "gid": info.st_gid,
            },
            {"path": str(absent), "present": False},
        ],
        "service_before": {"enabled": True, "active": False},
    }
    evidence = INSTALLER.restored_checkpoint_evidence(
        record, lambda: {"enabled": True, "active": False}
    )
    assert evidence["service"] == {"enabled": True, "active": False}
    assert evidence["files"] == [
        {
            "path": str(target),
            "present": True,
            "sha256": hashlib.sha256(expected).hexdigest(),
        },
        {"path": str(absent), "present": False},
    ]
    target.write_bytes(b"displaced\n")
    with pytest.raises(INSTALLER.InstallError, match="differs from checkpoint"):
        INSTALLER.restored_checkpoint_evidence(
            record, lambda: {"enabled": True, "active": False}
        )
    target.write_bytes(expected)
    target.chmod(0o640)
    with pytest.raises(INSTALLER.InstallError, match="service state read-back"):
        INSTALLER.restored_checkpoint_evidence(
            record, lambda: {"enabled": True, "active": True}
        )


def test_rollback_pass_record_follows_post_restore_readback() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    restore = source.index("restored = restore_checkpoint(")
    completion = source.index('"completed_at_utc"', restore)
    evidence = source.index('"restored": restored', completion)
    write = source.index("atomic_write(checkpoint / ROLLBACK_RESULT_NAME", evidence)
    readback = source.index("persisted = completed_rollback_result(", write)
    returned = source.index("return persisted", readback)
    assert restore < completion < evidence < write < readback < returned


def test_snapshot_persists_new_backup_ancestry_before_first_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup_root = tmp_path / "new-parent" / "host-auditd"
    stamp = "20260902T001500Z"
    events: list[tuple[str, Path]] = []
    real_fsync_directory = INSTALLER.fsync_directory

    def fsync_directory(path: Path) -> None:
        events.append(("fsync", Path(path)))
        real_fsync_directory(path)

    def snapshot_file(path: Path, destination: Path) -> dict[str, object]:
        events.append(("snapshot", destination))
        return {"path": str(path), "present": False}

    monkeypatch.setattr(INSTALLER, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(INSTALLER, "stamp_now", lambda: stamp)
    monkeypatch.setattr(INSTALLER, "fsync_directory", fsync_directory)
    monkeypatch.setattr(INSTALLER, "snapshot_file", snapshot_file)
    returned_stamp, destination, _record = INSTALLER.snapshot_before(
        "a" * 40, {"enabled": False, "active": False}
    )
    assert returned_stamp == stamp
    assert destination == backup_root / stamp
    first_snapshot = next(
        index for index, event in enumerate(events) if event[0] == "snapshot"
    )
    assert ("fsync", backup_root.parent) in events[:first_snapshot]
    assert ("fsync", backup_root) in events[:first_snapshot]
    assert ("fsync", destination) in events[:first_snapshot]


def test_rollback_rejects_failed_durable_completion_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stamp = "20260901T120000Z"
    source_sha = "a" * 40
    checkpoint = tmp_path / stamp
    checkpoint.mkdir()
    calls = 0

    def completion_readback(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        raise INSTALLER.InstallError("durable rollback completion rejected")

    monkeypatch.setattr(INSTALLER, "BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(INSTALLER, "require_prerequisites", lambda: None)
    monkeypatch.setattr(INSTALLER, "completed_rollback_result", completion_readback)
    monkeypatch.setattr(
        INSTALLER,
        "restore_checkpoint",
        lambda *_args: {"files": [], "service": {"enabled": False, "active": False}},
    )
    args = argparse.Namespace(expected_source_sha=source_sha, backup_stamp=stamp)
    with pytest.raises(INSTALLER.InstallError, match="durable rollback completion"):
        INSTALLER.rollback(args)
    assert calls == 2


def test_rollback_authenticates_complete_root_only_checkpoint_before_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stamp = "20260901T120000Z"
    source_sha = "a" * 40
    backup_root = tmp_path / "backups"
    checkpoint = backup_root / stamp
    backup_root.mkdir(mode=0o700)
    checkpoint.mkdir(mode=0o700)
    monkeypatch.setattr(INSTALLER, "BACKUP_ROOT", backup_root)

    items = []
    for index, (target, snapshot_name) in enumerate(INSTALLER.SNAPSHOT_NAMES.items()):
        payload = f"snapshot-{index}\n".encode()
        snapshot = checkpoint / snapshot_name
        snapshot.write_bytes(payload)
        snapshot.chmod(0o600)
        items.append(
            {
                "path": str(target),
                "present": True,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "mode": 0o600,
                "uid": 0,
                "gid": 0,
                "snapshot": snapshot_name,
            }
        )
    record = {
        "schema": "codestra.host-auditd.rollback.v1",
        "stamp": stamp,
        "source_sha": source_sha,
        "service_before": {"enabled": True, "active": True},
        "files": items,
    }
    manifest = json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    (checkpoint / "rollback.json").write_bytes(manifest)
    (checkpoint / "SHA256SUMS").write_text(
        f"{hashlib.sha256(manifest).hexdigest()}  rollback.json\n"
    )
    (checkpoint / "rollback.json").chmod(0o600)
    (checkpoint / "SHA256SUMS").chmod(0o600)

    def local_authorities(paths: list[Path]) -> list[Path]:
        return sorted(
            {backup_root, checkpoint, *paths},
            key=lambda item: (len(item.parts), str(item)),
        )

    monkeypatch.setattr(INSTALLER, "path_authority_chain", local_authorities)
    monkeypatch.setattr(INSTALLER, "operator_cannot_modify", lambda paths: True)
    assert (
        INSTALLER.validate_rollback_checkpoint(checkpoint, source_sha, stamp)
        == record
    )

    displaced = checkpoint / items[0]["snapshot"]
    displaced.chmod(0o666)
    with pytest.raises(INSTALLER.InstallError, match="unsafe exact root metadata"):
        INSTALLER.validate_rollback_checkpoint(checkpoint, source_sha, stamp)
    displaced.chmod(0o600)
    unexpected = checkpoint / "attacker-extra"
    unexpected.write_text("unexpected\n")
    unexpected.chmod(0o600)
    with pytest.raises(INSTALLER.InstallError, match="unexpected files"):
        INSTALLER.validate_rollback_checkpoint(checkpoint, source_sha, stamp)


def test_completed_rollback_result_is_verified_and_reused_without_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stamp = "20260901T120000Z"
    source_sha = "a" * 40
    checkpoint = tmp_path / stamp
    checkpoint.mkdir()
    restored = {
        "files": [{"path": str(INSTALLER.RULE_TARGET), "present": False}],
        "service": {"enabled": False, "active": False},
    }
    result = {
        "schema": "codestra.host-auditd.rollback-result.v1",
        "source_sha": source_sha,
        "rollback_stamp": stamp,
        "completed_at_utc": "2026-09-01T12:00:00Z",
        "restored": restored,
        "mutation_scope": list(INSTALLER.ROLLBACK_MUTATION_SCOPE),
    }
    result_path = checkpoint / INSTALLER.ROLLBACK_RESULT_NAME
    result_path.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    result_path.chmod(0o600)
    checkpoint_record = {"files": [], "service_before": {}}
    monkeypatch.setattr(
        INSTALLER,
        "validate_rollback_checkpoint",
        lambda *args, **kwargs: checkpoint_record,
    )
    monkeypatch.setattr(
        INSTALLER, "restored_checkpoint_evidence", lambda record: restored
    )
    assert INSTALLER.completed_rollback_result(checkpoint, source_sha, stamp) == result

    monkeypatch.setattr(INSTALLER, "BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(INSTALLER, "require_prerequisites", lambda: None)
    monkeypatch.setattr(
        INSTALLER,
        "restore_checkpoint",
        lambda *args: pytest.fail("completed rollback must not mutate again"),
    )
    args = argparse.Namespace(expected_source_sha=source_sha, backup_stamp=stamp)
    assert INSTALLER.rollback(args) == result

    changed = dict(result)
    changed["source_sha"] = "b" * 40
    result_path.write_text(json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(INSTALLER.InstallError, match="rollback result identity"):
        INSTALLER.completed_rollback_result(checkpoint, source_sha, stamp)


def test_restore_reauthenticates_checkpoint_before_first_target_mutation() -> None:
    source = (PACKAGE / "install-provider-host-auditd.py").read_text()
    restore = source.split("def restore_checkpoint(", 1)[1].split(
        "def persist_installation_record", 1
    )[0]
    authenticate = restore.index("record = validate_rollback_checkpoint(")
    mutate = restore.index("restore_file(item, checkpoint)")
    assert authenticate < mutate


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


def test_validation_persists_new_evidence_directory_before_file_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    evidence_root = state_root / "evidence"
    target = evidence_root / "correlation.json"
    events: list[Path] = []
    real_fsync_directory = VALIDATOR.fsync_directory

    def fsync_directory(path: Path) -> None:
        events.append(Path(path))
        real_fsync_directory(path)

    monkeypatch.setattr(VALIDATOR, "fsync_directory", fsync_directory)
    VALIDATOR.durable_evidence(target, b'{"result":"PASS"}\n')
    assert events[:2] == [evidence_root, state_root]
    assert events[-1] == evidence_root


def test_validation_pass_is_emitted_only_after_durable_evidence() -> None:
    source = (PACKAGE / "validate-provider-host-auditd.py").read_text()
    durable = source.index("digest, size = durable_evidence(destination, payload)")
    result = source.index('"result": "PASS"', durable)
    output = source.index("print(json.dumps(", durable)
    assert durable < result < output
    assert "complete environment" not in source.lower()
    assert "os.environ" not in source


@pytest.mark.parametrize("kind", ["fifo", "symlink", "hardlink", "writable", "group"])
def test_validator_rejects_unsafe_lock_before_validation(tmp_path, monkeypatch, kind):
    from unittest.mock import Mock
    lock = tmp_path / "lock"
    if kind == "fifo":
        os.mkfifo(lock, 0o600)
    elif kind == "symlink":
        target = tmp_path / "target"
        target.touch(mode=0o600)
        lock.symlink_to(target)
    else:
        lock.touch(mode=0o600)
        if kind == "hardlink": os.link(lock, tmp_path / "alias")
        elif kind == "writable": lock.chmod(0o666)
    validate = Mock()
    persist = Mock()
    real_fstat = os.fstat
    def lock_metadata(fd):
        info = real_fstat(fd)
        return SimpleNamespace(st_mode=info.st_mode, st_nlink=info.st_nlink,
                               st_uid=0, st_gid=12345 if kind == "group" else 0)
    monkeypatch.setattr(VALIDATOR.os, "fstat", lock_metadata)
    monkeypatch.setattr(VALIDATOR, "MUTATION_LOCK", lock)
    monkeypatch.setattr(VALIDATOR, "validate", validate)
    monkeypatch.setattr(VALIDATOR, "durable_evidence", persist)
    assert VALIDATOR.main(["--expected-source-sha", "a" * 40]) == 1
    validate.assert_not_called()
    persist.assert_not_called()
