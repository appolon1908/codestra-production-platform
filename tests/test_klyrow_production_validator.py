from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "operations" / "klyrow-production-validator"
sys.path.insert(0, str(SOURCE))

from klyrow_validator_core import (  # noqa: E402
    APPROVED_ACTIONS,
    ExclusiveLock,
    PolicyError,
    append_audit,
    limited_command,
    parse_direct,
    parse_ssh_original_command,
    redact_object,
    redact_text,
    regular_nonsymlink,
    reject_dangerous_environment,
    safe_json_file,
)


def load_source_script(filename: str, name: str):
    path = SOURCE / filename
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_actions_module():
    return load_source_script(
        "klyrow-production-validator-actions", "klyrow_production_validator_actions"
    )


NEGATIVE_COMMANDS = (
    "bash",
    "sh",
    "sudo -s",
    "sudo bash",
    "docker exec klyrow-gateway-1 sh",
    "docker inspect arbitrary-container",
    "docker compose up",
    "docker compose restart",
    "cat /etc/shadow",
    "cat /run/secrets/provider",
    "cat /proc/1/environ",
    "status > /tmp/output",
    "$(id)",
    "status; id",
    "status | id",
    "status\nid",
    "../../etc/shadow",
    "klyrow-production-validator status --verbose",
    "klyrow-production-validator  status",
    "klyrow-production-validator canary",
)


@pytest.mark.parametrize("action", APPROVED_ACTIONS)
def test_every_approved_direct_action_is_recognized(action: str) -> None:
    assert parse_direct([action]) == action


@pytest.mark.parametrize("action", APPROVED_ACTIONS)
def test_every_approved_ssh_action_is_recognized(action: str) -> None:
    assert parse_ssh_original_command(f"klyrow-production-validator {action}") == action


@pytest.mark.parametrize("command", NEGATIVE_COMMANDS)
def test_prohibited_commands_are_rejected(command: str) -> None:
    with pytest.raises(PolicyError):
        parse_ssh_original_command(command)


@pytest.mark.parametrize("argv", [[], ["status", "extra"], ["bash"], ["../status"], ["status;id"]])
def test_missing_extra_and_unknown_direct_actions_are_rejected(argv: list[str]) -> None:
    with pytest.raises(PolicyError):
        parse_direct(argv)


@pytest.mark.parametrize("command", [None, "", "status\r", "status\n", "status\x00id"])
def test_malformed_ssh_commands_are_rejected(command: str | None) -> None:
    with pytest.raises(PolicyError):
        parse_ssh_original_command(command)


def test_dangerous_environment_is_rejected() -> None:
    for name in ("LD_PRELOAD", "PYTHONPATH", "BASH_ENV", "DOCKER_HOST", "COMPOSE_FILE", "IFS"):
        with pytest.raises(PolicyError):
            reject_dangerous_environment({name: "unsafe"})


def test_secrets_are_redacted_from_text_and_structures() -> None:
    raw = (
        "Authorization: Bearer abc.def password=hunter2 API_KEY=xyz "
        + "-----BEGIN " + "PRIVATE KEY-----secret-----END " + "PRIVATE KEY-----"
    )
    redacted = redact_text(raw)
    assert "abc.def" not in redacted
    assert "hunter2" not in redacted
    assert "xyz" not in redacted
    assert "PRIVATE KEY-----secret" not in redacted
    structured = redact_object({"client_secret": "hidden", "nested": {"token": "hidden2"}})
    assert structured == {"client_secret": "[REDACTED]", "nested": {"token": "[REDACTED]"}}


def test_output_is_bounded_and_safely_truncated() -> None:
    result = limited_command(
        ["/usr/bin/python3", "-c", "import sys; sys.stdout.write('x'*200000)"],
        timeout_seconds=5,
        maximum_output_bytes=1024,
    )
    assert result.returncode == 0
    assert result.truncated is True
    assert len(result.stdout.encode()) <= 1024


def test_timeout_terminates_the_child_process() -> None:
    result = limited_command(
        ["/usr/bin/python3", "-c", "import time; time.sleep(30)"],
        timeout_seconds=1,
        maximum_output_bytes=1024,
    )
    assert result.returncode == 124
    assert result.timed_out is True
    assert result.elapsed_ms < 5000


def test_non_absolute_executable_is_rejected() -> None:
    with pytest.raises(PolicyError):
        limited_command(["python3", "-V"], timeout_seconds=1, maximum_output_bytes=10)


def test_symlink_and_group_writable_files_are_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.write_text("safe", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(PolicyError):
        regular_nonsymlink(link, allowed_owners=(os.getuid(),))
    real.chmod(0o666)
    with pytest.raises(PolicyError):
        regular_nonsymlink(real, allowed_owners=(os.getuid(),))


def test_json_readback_rejects_secret_and_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "readback.json"
    path.write_text('{"safe":true,"token":"secret"}', encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(PolicyError):
        safe_json_file(path, allowed_keys={"safe", "token"}, allowed_owners=(os.getuid(),))
    path.write_text('{"unexpected":true}', encoding="utf-8")
    with pytest.raises(PolicyError):
        safe_json_file(path, allowed_keys={"safe"}, allowed_owners=(os.getuid(),))


def test_audit_records_are_created_and_redacted(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    append_audit(path, {"action": "status", "token": "secret", "result": "PASS"})
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["action"] == "status"
    assert record["token"] == "[REDACTED]"
    assert "secret" not in path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o777 == 0o600


def test_concurrency_lock_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "operator.lock"
    with ExclusiveLock(path):
        with pytest.raises(PolicyError, match="OPERATOR_BUSY"):
            with ExclusiveLock(path):
                pass


def test_command_contract_is_default_deny_and_complete() -> None:
    contract = json.loads((SOURCE / "command-contract.json").read_text(encoding="utf-8"))
    assert contract["default"] == "deny"
    assert contract["allowed_user"] == "codestra-admin"
    assert set(contract["actions"]) == set(APPROVED_ACTIONS)
    assert "canary" in contract["prohibited_actions"]
    assert "docker" in contract["prohibited_actions"]
    assert contract["fixed_targets"]["listener_ports"] == [25, 587, 2525, 18000]
    for action, entry in contract["actions"].items():
        assert entry["fixed_arguments"] == [action]
        assert entry["fixed_executable"].startswith("/usr/local/libexec/")
        assert entry["timeout_seconds"] > 0
        assert entry["maximum_output_bytes"] <= 262144
        assert entry["mutation_classification"] == "read_only_no_effect"
        assert entry["rollback_requirement"] == "none"


def test_sudoers_contains_only_exact_helper_actions() -> None:
    value = (SOURCE / "klyrow-production-validator.sudoers").read_text(encoding="utf-8")
    assert " NOPASSWD: KLYROW_VALIDATOR" in value
    assert " ALL=(ALL)" not in value
    assert "/usr/bin/docker" not in value
    assert "/bin/bash" not in value
    assert "/bin/sh" not in value
    for action in APPROVED_ACTIONS:
        assert f"klyrow-production-validator-root {action}" in value


def test_authorized_keys_template_enforces_ssh_boundaries() -> None:
    value = (SOURCE / "authorized_keys.template").read_text(encoding="utf-8")
    for fragment in (
        "from=",
        "expiry-time=",
        'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch"',
        "restrict",
        "no-agent-forwarding",
        "no-port-forwarding",
        "no-X11-forwarding",
        "no-pty",
        "no-user-rc",
    ):
        assert fragment in value


def test_dispatcher_and_root_helper_share_one_validated_correlation_id() -> None:
    dispatcher = (SOURCE / "klyrow-production-validator").read_text(encoding="utf-8")
    helper = (SOURCE / "klyrow-production-validator-root").read_text(encoding="utf-8")
    assert 'input=correlation_id + "\\n"' in dispatcher
    assert "correlation_id = read_correlation_id()" in helper
    assert "CORRELATION_RE.fullmatch(correlation_id)" in helper


def test_health_output_never_selects_health_log_output() -> None:
    actions = (SOURCE / "klyrow-production-validator-actions").read_text(encoding="utf-8")
    assert "{{json .State.Health.Status}}" in actions
    assert "{{json .State.Health}}" not in actions
    assert ".State.Health.Log" not in actions


def test_health_requires_every_container_to_report_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    actions = load_actions_module()
    statuses = iter(('"healthy"\n', '"unhealthy"\n', '"starting"\n', 'null\n'))

    def fake_run(argv: list[str], **_kwargs: object) -> dict[str, object]:
        assert argv[:3] == ["/usr/bin/docker", "inspect", "--format"]
        return {
            "argv_id": "docker",
            "exit_code": 0,
            "stdout": next(statuses),
            "stderr": "",
            "elapsed_ms": 1,
            "truncated": False,
            "timed_out": False,
        }

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _maximum: int) -> bytes:
            return b'{}'

    monkeypatch.setattr(actions, "run", fake_run)
    monkeypatch.setattr(actions.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    assert actions.health() == 3


def release_container(actions, name: str) -> dict[str, object]:
    return {
        "name": name,
        "image_repository": "ghcr.io/codestra/klyrow",
        "image_digest": "sha256:" + "a" * 64,
        "oci_source_revision": "b" * 40,
        "source_repository": "appolon1908-hue/klyrow.com",
        "source_commit_sha": "b" * 40,
        "release_change_id": "KLYROW-20260831-01",
        "build_workflow_run": "github:123456",
        "sbom_digest": "sha256:" + "c" * 64,
        "provenance_reference": "github:attestation/123456",
        "signature_verification": "PASS",
        "vulnerability_scan_result": "PASS",
        "configuration_checksum": "sha256:" + "d" * 64,
    }


def release_readback(actions) -> dict[str, object]:
    return {
        "containers": [release_container(actions, name) for name in actions.CONTAINERS],
        "contract_compatibility": "PASS",
        "mutable_image_references": 0,
        "source_provenance_match": "YES",
        "signature_verification": "PASS",
        "vulnerability_gate": "PASS",
        "generated_at_utc": "2026-08-31T15:00:00Z",
    }


def test_release_identity_projects_only_exact_recursive_schema() -> None:
    actions = load_actions_module()
    value = release_readback(actions)
    assert actions.projected_release_identity(value) == value
    value["containers"][0]["environment"] = {"DATABASE_URL": "secret"}
    with pytest.raises(PolicyError, match="RELEASE_CONTAINER_SCHEMA_REJECTED"):
        actions.projected_release_identity(value)


def test_release_identity_rejects_secret_shaped_nested_replacement() -> None:
    actions = load_actions_module()
    value = release_readback(actions)
    value["containers"][0]["provenance_reference"] = "https://user:password@example.invalid"
    with pytest.raises(PolicyError, match="RELEASE_PROVENANCE_REFERENCE_REJECTED"):
        actions.projected_release_identity(value)


def test_release_identity_rejects_nested_top_level_status_values() -> None:
    actions = load_actions_module()
    value = release_readback(actions)
    value["signature_verification"] = {"client_secret": "hidden"}
    with pytest.raises(PolicyError, match="RELEASE_SIGNATURE_VERIFICATION_REJECTED"):
        actions.projected_release_identity(value)


def test_inventory_commands_are_scoped_to_approved_workloads_and_ports() -> None:
    actions = (SOURCE / "klyrow-production-validator-actions").read_text(encoding="utf-8")
    assert 'f"name=^/{container}$"' in actions
    assert '["/usr/bin/ss", "-H", "-lntp"]' not in actions
    assert 'f":{port}"' in actions


def test_no_effect_authority_rejects_nested_or_unsafe_emitted_values() -> None:
    probe = load_source_script("probe-no-effect-tests", "kpv_probe_no_effect")
    authority = {
        "adapter": "codestra:no-effect-adapter/v1",
        "adapter_sha256": "a" * 64,
        "suppressed_synthetic_recipient_authorized": True,
        "denied_consent_synthetic_recipient_authorized": True,
        "provider_submission_impossible": True,
        "approved_by": "independent-reviewer",
        "expires_at_utc": "2099-12-31T23:59:59Z",
    }
    assert probe.project_authority(authority)["adapter"] == authority["adapter"]
    authority["adapter"] = {"database_url": "postgres://secret"}
    with pytest.raises(ValueError, match="adapter rejected"):
        probe.project_authority(authority)


def test_forced_key_parser_requires_exact_options_and_binds_fingerprint(tmp_path: Path) -> None:
    validator = load_source_script(
        "validate-klyrow-production-validator.py", "kpv_installation_validator"
    )
    key = tmp_path / "operator-key"
    run_checked(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
    key_type, key_blob, *_ = key.with_suffix(".pub").read_text(encoding="ascii").split()
    line = (
        'from="192.0.2.0/24",expiry-time="20991231235959Z",'
        'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch",'
        "restrict,no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty,no-user-rc "
        f"{key_type} {key_blob}"
    )
    details = validator.forced_key_details(line)
    expected_fingerprint = run_checked(
        ["/usr/bin/ssh-keygen", "-lf", str(key.with_suffix(".pub"))]
    ).stdout.split()[1]
    assert details == {
        "source_restriction": "192.0.2.0/24",
        "expires_at": "20991231235959Z",
        "key_fingerprint": expected_fingerprint,
    }
    assert validator.forced_key_details(line.replace("no-port-forwarding,", "")) is None
    assert validator.forced_key_details(line.replace("192.0.2.0/24", "0.0.0.0/0")) is None


def test_pull_request_validation_token_is_read_only() -> None:
    workflow = (SOURCE.parents[1] / ".github/workflows/klyrow-production-validator.yml").read_text(
        encoding="utf-8"
    )
    assert "permissions:\n  contents: read" in workflow
    validate_job = workflow.split("  validate-operator:", 1)[1].split(
        "  publish-protected-artifact:", 1
    )[0]
    assert "contents: write" not in validate_job
    assert "persist-credentials: false" in validate_job
    assert "ref: ${{ env.OPERATOR_SOURCE_SHA }}" in validate_job
    assert 'test "$(git rev-parse HEAD)" = "${OPERATOR_SOURCE_SHA}"' in validate_job


def test_pinned_probes_are_bundled_and_structurally_no_data() -> None:
    required = (
        "kpv_probe_core.py",
        "probe-authorization-tests",
        "probe-no-effect-tests",
        "probe-callback-tests",
        "probe-smtp-no-data",
    )
    for name in required:
        assert (SOURCE / name).is_file()
    smtp = (SOURCE / "probe-smtp-no-data").read_text(encoding="utf-8").lower()
    assert ".data(" not in smtp
    assert "sendmail" not in smtp
    assert 'docmd("mail"' in smtp
    assert 'docmd("rcpt"' in smtp
    no_effect = (SOURCE / "probe-no-effect-tests").read_text(encoding="utf-8")
    assert "tests_executed\": False" in no_effect
    assert "provider_submissions\": 0" in no_effect


def test_installer_never_grants_host_groups_or_generic_privilege() -> None:
    installer = (SOURCE / "install-klyrow-production-validator.py").read_text(encoding="utf-8")
    for forbidden in ("groupadd", "groupmod", "usermod", "chmod 666", "docker.sock"):
        assert forbidden not in installer


def run_checked(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, check=True, **kwargs)


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="OpenSSH tooling unavailable")
def test_disposable_install_revocation_validation_and_rollback() -> None:
    source_sha = "a" * 40
    with tempfile.TemporaryDirectory(prefix="kpv-test-release-") as release_name, tempfile.TemporaryDirectory(
        prefix="kpv-simulator-", dir="/tmp"
    ) as simulator_name:
        release = Path(release_name)
        simulator = Path(simulator_name)
        (simulator / ".kpv-disposable-simulator").write_text("disposable\n", encoding="utf-8")
        run_checked(
            [
                "/usr/bin/python3",
                str(SOURCE / "build-operator-artifact.py"),
                "--source-sha",
                source_sha,
                "--output",
                str(release),
                "--workflow-run",
                "pytest",
            ]
        )
        release_key = release / "release-key"
        operator_key = release / "operator-key"
        run_checked(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(release_key)])
        run_checked(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(operator_key)])
        signers = release / "allowed_signers"
        public_release = (release_key.with_suffix(".pub")).read_text(encoding="ascii").strip()
        signers.write_text(f"codestra-release {public_release}\n", encoding="ascii")
        signers.chmod(0o600)
        sums = release / "SHA256SUMS"
        run_checked(
            [
                "/usr/bin/ssh-keygen",
                "-Y",
                "sign",
                "-q",
                "-f",
                str(release_key),
                "-n",
                "codestra-klyrow-validator",
                str(sums),
            ]
        )
        archive = release / f"klyrow-production-validator-{source_sha}.tar.gz"
        install = run_checked(
            [
                "/usr/bin/python3",
                str(SOURCE / "install-klyrow-production-validator.py"),
                "--archive",
                str(archive),
                "--sha256s",
                str(sums),
                "--signature",
                str(sums) + ".sig",
                "--allowed-signers",
                str(signers),
                "--public-key",
                str(operator_key) + ".pub",
                "--source-cidr",
                "192.0.2.0/24",
                "--expiry",
                "20991231235959Z",
                "--approver",
                "independent-reviewer",
                "--change-id",
                "KPV-20260831-01",
                "--simulator-root",
                str(simulator),
            ]
        )
        assert "INSTALL_RESULT=PASS" in install.stdout
        validation = run_checked(
            [
                "/usr/bin/python3",
                str(SOURCE / "validate-klyrow-production-validator.py"),
                "--expected-source-sha",
                source_sha,
                "--simulator-root",
                str(simulator),
            ]
        )
        assert '"validation_result": "PASS"' in validation.stdout
        authorized = simulator / "home/codestra-admin/.ssh/authorized_keys"
        authorized_original = authorized.read_text(encoding="utf-8")
        authorized.write_text(
            authorized_original.replace('from="192.0.2.0/24"', 'from="0.0.0.0/0"'),
            encoding="utf-8",
        )
        authorized.chmod(0o600)
        tampered_validation = subprocess.run(
            [
                "/usr/bin/python3",
                str(SOURCE / "validate-klyrow-production-validator.py"),
                "--expected-source-sha",
                source_sha,
                "--simulator-root",
                str(simulator),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert tampered_validation.returncode == 3
        assert '"validation_result": "FAIL"' in tampered_validation.stdout
        authorized.write_text(authorized_original, encoding="utf-8")
        authorized.chmod(0o600)
        restored_validation = run_checked(
            [
                "/usr/bin/python3",
                str(SOURCE / "validate-klyrow-production-validator.py"),
                "--expected-source-sha",
                source_sha,
                "--simulator-root",
                str(simulator),
            ]
        )
        assert '"validation_result": "PASS"' in restored_validation.stdout
        probe_manifest = simulator / "etc/codestra/klyrow-production-validator/probe-manifest.json"
        installed_probes = json.loads(probe_manifest.read_text(encoding="utf-8"))
        assert set(installed_probes["probes"]) == {
            "authorization-tests",
            "no-effect-tests",
            "callback-tests",
            "smtp-no-data",
        }
        fingerprint = run_checked(["/usr/bin/ssh-keygen", "-lf", str(operator_key) + ".pub"]).stdout.split()[1]
        revoked = run_checked(
            [
                "/usr/bin/python3",
                str(SOURCE / "revoke-klyrow-validator-key.py"),
                "--expected-fingerprint",
                fingerprint,
                "--simulator-root",
                str(simulator),
            ]
        )
        assert "REVOCATION_RESULT=PASS" in revoked.stdout
        assert 'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch"' not in authorized.read_text(encoding="utf-8")
        rollback = run_checked(
            [
                "/usr/bin/python3",
                str(SOURCE / "remove-klyrow-production-validator.py"),
                "--expected-source-sha",
                source_sha,
                "--simulator-root",
                str(simulator),
            ]
        )
        assert "ROLLBACK_RESULT=PASS" in rollback.stdout
        assert not (simulator / "usr/local/libexec/codestra/klyrow-production-validator").exists()
        assert not (simulator / f"opt/codestra/operators/klyrow-production-validator/{source_sha}").exists()


def test_artifact_build_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    source_sha = "b" * 40
    for destination in (first, second):
        run_checked(
            [
                "/usr/bin/python3",
                str(SOURCE / "build-operator-artifact.py"),
                "--source-sha",
                source_sha,
                "--output",
                str(destination),
                "--workflow-run",
                "same-run",
            ]
        )
    first_archive = first / f"klyrow-production-validator-{source_sha}.tar.gz"
    second_archive = second / first_archive.name
    assert hashlib.sha256(first_archive.read_bytes()).digest() == hashlib.sha256(second_archive.read_bytes()).digest()
    assert (first / "SHA256SUMS").read_bytes() == (second / "SHA256SUMS").read_bytes()
