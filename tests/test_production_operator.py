from __future__ import annotations

import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
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
REAL_VALIDATE_DATABASE_CERTIFICATION = OPERATOR.validate_database_certification


@pytest.fixture(autouse=True)
def _validated_database_certification(monkeypatch):
    monkeypatch.setattr(
        OPERATOR,
        "validate_database_certification",
        lambda: {"production_database_certification": "PASS"},
    )


def _model_root_owned_test_files(monkeypatch) -> None:
    """Model root-owned fixtures without requiring pytest itself to run as root."""
    real_lstat = OPERATOR.Path.lstat

    def root_owned(info):
        values = list(info)
        values[4] = 0
        values[5] = 0
        return os.stat_result(values)

    def checked_root_fixture_bytes(path, *, expected_mode=0o600):
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
        except OSError as error:
            if error.errno == OPERATOR.errno.ELOOP:
                raise OPERATOR.OperatorError(f"unsafe file type: {path}") from error
            raise OPERATOR.OperatorError(
                f"required root file unavailable: {path}"
            ) from error
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not OPERATOR.stat.S_ISREG(info.st_mode):
                raise OPERATOR.OperatorError(f"unsafe file type: {path}")
            if info.st_uid != os.geteuid() or info.st_gid != os.getegid():
                raise OPERATOR.OperatorError(f"unsafe fixture ownership: {path}")
            if OPERATOR.stat.S_IMODE(info.st_mode) != expected_mode:
                raise OPERATOR.OperatorError(f"unsafe mode: {path}")
            return stream.read()

    monkeypatch.setattr(OPERATOR, "checked_root_bytes", checked_root_fixture_bytes)
    monkeypatch.setattr(
        OPERATOR.Path,
        "lstat",
        lambda path: root_owned(real_lstat(path)),
    )


def test_root_owned_fixture_model_preserves_effective_operator_identity(
    monkeypatch, tmp_path
) -> None:
    fixture = tmp_path / "ownership-model"
    fixture.write_bytes(b"fixture")
    fixture.chmod(0o600)
    _model_root_owned_test_files(monkeypatch)

    with fixture.open("rb") as stream:
        info = OPERATOR.os.fstat(stream.fileno())
    assert (info.st_uid, info.st_gid) == (os.geteuid(), os.getegid())
    assert OPERATOR.checked_root_bytes(fixture) == b"fixture"
    assert OPERATOR.checked_operator_bytes(fixture, expected_mode=0o600) == b"fixture"


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
    "kong-readback",
    "stage-control-plane",
    "validate-control-plane",
    "rollback-control-plane",
    "rollout-middleware",
    "rollback-middleware",
    "activate-control-plane",
    "enable-production-web-traffic",
    "disable-production-web-traffic",
    "enable-klyrow-email-delivery",
    "disable-klyrow-email-delivery",
}


def test_action_set_is_exact() -> None:
    assert OPERATOR.ALLOWED_ACTIONS == EXPECTED_ACTIONS
    assert OPERATOR.SYSTEMD_ACTIONS == {
        "backup": "codestra-readiness-backup.service",
        "restore-test": "codestra-readiness-restore.service",
    }


def test_klyrow_authorization_requires_exact_tuple(monkeypatch) -> None:
    config = {
        "protected_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "change_id": "CHG-20260905-CODESTRA-PRODUCTION-ACTIVATION-01",
        "maintenance_date": "2026-09-05",
    }
    authorization = {
        "schema": "codestra.klyrow-email-authorization.v1", "approved": True,
        "change_id": config["change_id"], "protected_sha": config["protected_sha"],
        "maintenance_date": config["maintenance_date"],
        "klyrow_backup": "/var/backups/codestra-operators/klyrow/20260905T085512Z",
        "klyrow_evidence_sha256": "c" * 64, "verified_domains": 14,
        "held_messages": 2, "smtp_no_data": "PASS", "authorization_tests": "PASS",
        "owner": "release-owner",
    }
    monkeypatch.setattr(OPERATOR, "checked_root_file", lambda *_args, **_kwargs: json.dumps(authorization))
    evidence = OPERATOR.validate_klyrow_email_authorization(config)
    assert evidence["authorization"] == "PASS"
    assert evidence["verified_domains"] == 14
    authorization["authorization_tests"] = "FAIL"
    with pytest.raises(OPERATOR.OperatorError, match="authorization test evidence mismatch"):
        OPERATOR.validate_klyrow_email_authorization(config)
    authorization["authorization_tests"] = "PASS"
    authorization["verified_domains"] = 13
    with pytest.raises(OPERATOR.OperatorError, match="domain or held-message evidence mismatch"):
        OPERATOR.validate_klyrow_email_authorization(config)
    authorization["verified_domains"] = 14
    authorization["protected_sha"] = "d" * 40
    with pytest.raises(OPERATOR.OperatorError, match="protected_sha mismatch"):
        OPERATOR.validate_klyrow_email_authorization(config)


def test_database_certification_blocks_activation_without_manifest_pass(
    monkeypatch,
):
    monkeypatch.setattr(
        OPERATOR,
        "run_fixed",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "PRODUCTION_DATABASE_MANIFEST=PASS\n", ""),
    )
    monkeypatch.setattr(
        OPERATOR,
        "checked_root_file",
        lambda *args, **kwargs: "certification_status: FAIL\n",
    )
    with pytest.raises(OPERATOR.OperatorError, match="certification is not PASS"):
        REAL_VALIDATE_DATABASE_CERTIFICATION()


def test_database_certification_requires_validator_success(monkeypatch):
    monkeypatch.setattr(
        OPERATOR,
        "run_fixed",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "invalid evidence"),
    )
    with pytest.raises(OPERATOR.OperatorError, match="certification is not PASS"):
        REAL_VALIDATE_DATABASE_CERTIFICATION()


def test_run_fixed_supports_bounded_timeout(monkeypatch):
    observed = {}

    def fake_run(command, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(OPERATOR.subprocess, "run", fake_run)
    OPERATOR.run_fixed(["/usr/bin/true"], timeout=30)
    assert observed["timeout"] == 30


def test_installer_validates_certified_manifest_against_evidence_root():
    installer = (PACKAGE / "install-server-a-operator.sh").read_text()
    assert "/opt/codestra/evidence/database-certification" in installer
    assert 'validate_trusted_source "$database_manifest_source"' in installer
    assert 'validate_trusted_source "$database_validator_source"' in installer


def test_web_traffic_health_revalidates_database_certification():
    source = OPERATOR_PATH.read_text()
    function = source.split("def core_web_health", 1)[1].split("\ndef ", 1)[0]
    assert "validate_database_certification()" in function


def test_control_plane_stage_builds_and_reads_back_protected_sha() -> None:
    source = OPERATOR_PATH.read_text()
    assert 'f"VCS_REF={config[\'protected_sha\']}"' in source
    assert 'api_env.get("SOURCE_SHA") != config["protected_sha"]' in source
    assert 'api_env.get("RELEASE_ID") != config["protected_sha"]' in source
    assert "control-plane version endpoint readback mismatch" in source


def test_fixed_probes_cannot_consume_operator_credentials() -> None:
    source = OPERATOR_PATH.read_text()
    assert "stdin=subprocess.DEVNULL" in source


def _archive(tmp_path: Path, member: tarfile.TarInfo) -> Path:
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        payload = b"safe"
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))
    return archive


def test_control_plane_archive_accepts_fixed_root(tmp_path: Path) -> None:
    archive = _archive(tmp_path, tarfile.TarInfo("codestra/control_plane_service/core.py"))
    OPERATOR.validate_control_plane_archive(archive, "e" * 40)


@pytest.mark.parametrize(
    "name,typecode,linkname",
    [
        ("../escape", tarfile.REGTYPE, ""),
        ("codestra/../../escape", tarfile.REGTYPE, ""),
        ("unexpected/file", tarfile.REGTYPE, ""),
        ("codestra/link", tarfile.SYMTYPE, "/etc/passwd"),
        ("codestra/hardlink", tarfile.LNKTYPE, "codestra/file"),
    ],
)
def test_control_plane_archive_rejects_unsafe_members(
    tmp_path: Path, name: str, typecode: bytes, linkname: str
) -> None:
    member = tarfile.TarInfo(name)
    member.type = typecode
    member.linkname = linkname
    archive = _archive(tmp_path, member)
    with pytest.raises(OPERATOR.OperatorError, match="member rejected"):
        OPERATOR.validate_control_plane_archive(archive, "e" * 40)


def test_wait_control_plane_health_accepts_scheduled_probe(monkeypatch):
    states = iter(["starting", "starting", "healthy"])
    monkeypatch.setattr(
        OPERATOR,
        "docker_inspect",
        lambda _container: {"State": {"Health": {"Status": next(states)}}},
    )
    monkeypatch.setattr(OPERATOR.time, "sleep", lambda _seconds: None)

    OPERATOR.wait_control_plane_health(timeout_seconds=120)


def test_wait_control_plane_health_rejects_unhealthy(monkeypatch):
    monkeypatch.setattr(
        OPERATOR,
        "docker_inspect",
        lambda _container: {"State": {"Health": {"Status": "unhealthy"}}},
    )

    with pytest.raises(OPERATOR.OperatorError, match="became unhealthy"):
        OPERATOR.wait_control_plane_health(timeout_seconds=120)


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


def test_activation_requires_exact_stage_and_validation_evidence(monkeypatch):
    required = []
    monkeypatch.setattr(
        OPERATOR,
        "require_action_evidence",
        lambda action, config: required.append(action) or Path(f"/{action}.json"),
    )
    monkeypatch.setattr(OPERATOR, "validate_backup_state", lambda: {"backup_stamp": "20260823T000000Z"})
    bindings = []
    monkeypatch.setattr(
        OPERATOR,
        "require_evidence_value",
        lambda path, key, value: bindings.append((path, key, value)),
    )
    monkeypatch.setattr(OPERATOR, "validate_control_plane_rollback", lambda: {"rollback_stamp": "20260823T000001Z"})
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda config: {
            "stamp": "20260823T000002Z",
            "bundle_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(OPERATOR, "load_pointer", lambda path: None)
    monkeypatch.setattr(OPERATOR, "validate_control_plane", lambda config: {"control_plane": "PASS"})
    monkeypatch.setattr(OPERATOR, "verify_middleware_runtime", lambda config: {"middleware_runtime_digest": "PASS"})
    written = {}
    monkeypatch.setattr(OPERATOR, "atomic_root_json", lambda path, value: written.update(value))
    config = OPERATOR.load_release_config()
    result = OPERATOR.activate_control_plane(config)
    assert written["protected_sha"] == config["protected_sha"]
    assert result["rollback_ready"] == "PASS"
    assert "rollout-middleware" in required
    assert bindings == [
        (Path("/restore-test.json"), "tested_backup_stamp", "20260823T000000Z"),
        (
            Path("/rollout-middleware.json"),
            "middleware_backup_stamp",
            "20260823T000002Z",
        ),
        (
            Path("/rollout-middleware.json"),
            "middleware_rollback_bundle_sha256",
            "a" * 64,
        ),
    ]
    assert written["middleware_backup_stamp"] == "20260823T000002Z"
    assert written["middleware_rollback_bundle_sha256"] == "a" * 64


def test_activation_rejects_missing_or_corrupt_middleware_rollback(monkeypatch):
    config = OPERATOR.load_release_config()
    monkeypatch.setattr(
        OPERATOR,
        "require_action_evidence",
        lambda action, value: Path(f"/{action}.json"),
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_backup_state",
        lambda: {"backup_stamp": "20260823T000000Z"},
    )
    monkeypatch.setattr(OPERATOR, "require_evidence_value", lambda *args: None)
    monkeypatch.setattr(
        OPERATOR,
        "validate_control_plane_rollback",
        lambda: {"rollback_stamp": "20260823T000001Z"},
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: (_ for _ in ()).throw(
            OPERATOR.OperatorError("Middleware rollback database dump checksum mismatch")
        ),
    )
    monkeypatch.setattr(
        OPERATOR,
        "load_pointer",
        lambda path: pytest.fail("activation state must remain untouched"),
    )

    with pytest.raises(
        OPERATOR.OperatorError,
        match="Middleware rollback database dump checksum mismatch",
    ):
        OPERATOR.activate_control_plane(config)


def test_activation_rejects_middleware_rollback_not_bound_to_rollout(monkeypatch):
    config = OPERATOR.load_release_config()
    evidence = Path("/rollout-middleware.json")
    monkeypatch.setattr(
        OPERATOR,
        "require_action_evidence",
        lambda action, value: evidence if action == "rollout-middleware" else Path(f"/{action}.json"),
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_backup_state",
        lambda: {"backup_stamp": "20260823T000000Z"},
    )

    def require_binding(path, key, expected):
        if key == "middleware_rollback_bundle_sha256":
            raise OPERATOR.OperatorError(
                "operator evidence middleware_rollback_bundle_sha256 mismatch"
            )

    monkeypatch.setattr(OPERATOR, "require_evidence_value", require_binding)
    monkeypatch.setattr(
        OPERATOR,
        "validate_control_plane_rollback",
        lambda: {"rollback_stamp": "20260823T000001Z"},
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": "20260823T000002Z",
            "bundle_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "load_pointer",
        lambda path: pytest.fail("activation state must remain untouched"),
    )

    with pytest.raises(
        OPERATOR.OperatorError,
        match="middleware_rollback_bundle_sha256 mismatch",
    ):
        OPERATOR.activate_control_plane(config)


def test_restore_test_records_one_stable_backup_stamp(monkeypatch):
    monkeypatch.setattr(
        OPERATOR,
        "require_maintenance_window",
        lambda: {
            "maintenance_date": "2026-08-22",
            "maintenance_window": "PASS",
            "owner_window_waiver_evidence": "NOT_REQUIRED",
            "window_check": "APPROVED_WINDOW",
        },
    )
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
        "validate_backup_state",
        lambda: {"backup_stamp": "20260830T180000Z", "evidence_integrity": "PASS"},
    )
    required = []
    monkeypatch.setattr(
        OPERATOR,
        "require_action_evidence",
        lambda action, config: required.append((action, config)) or Path("/stage.json"),
    )
    monkeypatch.setattr(OPERATOR, "certify_standby", lambda config: {"subject": "ok"})
    monkeypatch.setattr(
        OPERATOR,
        "validate_restore_result",
        lambda stamp, config: {
            "restore_evidence_stamp": "20260830T190000Z",
            "tested_backup_stamp": stamp,
            "tested_backup_evidence_integrity": "PASS",
            "isolated_middleware_migration": "PASS",
            "tested_middleware_database_head": "0056_klyrow_delivery_events",
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "run_fixed",
        lambda command: subprocess.CompletedProcess(command, 0, ""),
    )

    _, result = OPERATOR.execute("restore-test")

    assert result["tested_backup_stamp"] == "20260830T180000Z"
    assert result["tested_backup_evidence_integrity"] == "PASS"
    assert result["restore_evidence_stamp"] == "20260830T190000Z"
    assert result["isolated_middleware_migration"] == "PASS"
    assert [action for action, _ in required] == ["stage"]


def test_restore_result_binds_exact_backup_image_source_and_schema(monkeypatch, tmp_path):
    _model_root_owned_test_files(monkeypatch)
    root = tmp_path / "restore"
    root.mkdir(mode=0o700)
    stamp = "20260830T190000Z"
    backup_stamp = "20260830T180000Z"
    (root / "LAST_SUCCESS").write_text(stamp + "\n")
    (root / "LAST_SUCCESS").chmod(0o600)
    evidence = root / stamp
    evidence.mkdir(mode=0o700)
    config = OPERATOR.load_release_config()
    result = evidence / "RESTORE-RESULT.txt"
    result.write_text(
        "\n".join(
            (
                "RESTORE_REHEARSAL_GATE=PASS",
                f"RESTORE_BACKUP_STAMP={backup_stamp}",
                f"MIDDLEWARE_CANDIDATE_IMAGE={OPERATOR.MIDDLEWARE_IMAGE}@{config['image_digest']}",
                f"MIDDLEWARE_CANDIDATE_SOURCE_SHA={OPERATOR.MIDDLEWARE_REQUIRED_SOURCE_SHA}",
                f"MIDDLEWARE_MIGRATION_HEAD={OPERATOR.MIDDLEWARE_REQUIRED_DATABASE_HEAD}",
                "MIDDLEWARE_SCHEMA_TABLE_COUNT=2",
                "MIDDLEWARE_ISOLATED_MIGRATION_GATE=PASS",
                "MIDDLEWARE_MIGRATION_IDENTITY=mw_integration_api",
                "MIDDLEWARE_PRODUCTION_GRANTS_MATCH=PASS",
                "MIDDLEWARE_CANDIDATE_HEALTH_GATE=PASS",
                "MIDDLEWARE_CANDIDATE_READINESS_GATE=PASS",
                "MIDDLEWARE_CANDIDATE_DATABASE_READINESS=PASS",
            )
        )
        + "\n"
    )
    names = (
        "RESTORE-RESULT.txt",
        "ODOO-FILESTORE-VALIDATION.json",
        "PRODUCTION-MIDDLEWARE-ROLE-BASELINE.txt",
        "PRODUCTION-MIDDLEWARE-ROLE-AFTER.txt",
        "PRODUCTION-KEYCLOAK-ROLE-BASELINE.txt",
        "PRODUCTION-KEYCLOAK-ROLE-AFTER.txt",
        "RESTORED-MIDDLEWARE-MIGRATION-ROLE.txt",
    )
    records = []
    for name in names:
        path = evidence / name
        if name != "RESTORE-RESULT.txt":
            path.write_text(f"{name}\n")
        path.chmod(0o600)
        records.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")
    (evidence / "SHA256SUMS").write_text("\n".join(records) + "\n")
    (evidence / "SHA256SUMS").chmod(0o600)
    monkeypatch.setattr(OPERATOR, "READINESS_RESTORE_ROOT", root)

    validated = OPERATOR.validate_restore_result(backup_stamp, config)

    assert validated["restore_evidence_stamp"] == stamp
    assert validated["isolated_middleware_migration"] == "PASS"
    assert validated["tested_middleware_database_head"] == "0056_klyrow_delivery_events"


def test_restore_result_rejects_unadvertised_backup(monkeypatch, tmp_path):
    _model_root_owned_test_files(monkeypatch)
    root = tmp_path / "restore"
    root.mkdir(mode=0o700)
    (root / "LAST_SUCCESS").write_text("20260830T190000Z\n")
    (root / "LAST_SUCCESS").chmod(0o600)
    evidence = root / "20260830T190000Z"
    evidence.mkdir(mode=0o700)
    names = (
        "RESTORE-RESULT.txt",
        "ODOO-FILESTORE-VALIDATION.json",
        "PRODUCTION-MIDDLEWARE-ROLE-BASELINE.txt",
        "PRODUCTION-MIDDLEWARE-ROLE-AFTER.txt",
        "PRODUCTION-KEYCLOAK-ROLE-BASELINE.txt",
        "PRODUCTION-KEYCLOAK-ROLE-AFTER.txt",
        "RESTORED-MIDDLEWARE-MIGRATION-ROLE.txt",
    )
    config = OPERATOR.load_release_config()
    (evidence / "RESTORE-RESULT.txt").write_text(
        "RESTORE_REHEARSAL_GATE=PASS\n"
        "RESTORE_BACKUP_STAMP=20260830T170000Z\n"
        f"MIDDLEWARE_CANDIDATE_IMAGE={OPERATOR.MIDDLEWARE_IMAGE}@{config['image_digest']}\n"
        f"MIDDLEWARE_CANDIDATE_SOURCE_SHA={OPERATOR.MIDDLEWARE_REQUIRED_SOURCE_SHA}\n"
        f"MIDDLEWARE_MIGRATION_HEAD={OPERATOR.MIDDLEWARE_REQUIRED_DATABASE_HEAD}\n"
        "MIDDLEWARE_SCHEMA_TABLE_COUNT=2\n"
        "MIDDLEWARE_ISOLATED_MIGRATION_GATE=PASS\n"
        "MIDDLEWARE_MIGRATION_IDENTITY=mw_integration_api\n"
        "MIDDLEWARE_PRODUCTION_GRANTS_MATCH=PASS\n"
        "MIDDLEWARE_CANDIDATE_HEALTH_GATE=PASS\n"
        "MIDDLEWARE_CANDIDATE_READINESS_GATE=PASS\n"
        "MIDDLEWARE_CANDIDATE_DATABASE_READINESS=PASS\n"
    )
    records = []
    for name in names:
        path = evidence / name
        if name != "RESTORE-RESULT.txt":
            path.write_text(f"{name}\n")
        path.chmod(0o600)
        records.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")
    (evidence / "SHA256SUMS").write_text("\n".join(records) + "\n")
    (evidence / "SHA256SUMS").chmod(0o600)
    monkeypatch.setattr(OPERATOR, "READINESS_RESTORE_ROOT", root)

    with pytest.raises(OPERATOR.OperatorError, match="result binding mismatch"):
        OPERATOR.validate_restore_result("20260830T180000Z", config)


def test_restore_evidence_rejects_a_different_backup_stamp(tmp_path):
    evidence = tmp_path / "restore-test.json"
    evidence.write_text('{"tested_backup_stamp":"20260830T170000Z"}\n')
    evidence.chmod(0o600)

    with pytest.raises(OPERATOR.OperatorError, match="tested_backup_stamp mismatch"):
        OPERATOR.require_evidence_value(
            evidence,
            "tested_backup_stamp",
            "20260830T180000Z",
        )


def test_middleware_rollout_requires_recovery_evidence_and_reads_schema(monkeypatch):
    config = OPERATOR.load_release_config()
    evidence = []
    calls = []
    monkeypatch.setattr(
        OPERATOR,
        "require_action_evidence",
        lambda action, value: evidence.append(action) or Path(f"/{action}.json"),
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_backup_state",
        lambda: {"backup_stamp": "20260830T180000Z"},
    )
    restore_bindings = []
    monkeypatch.setattr(
        OPERATOR,
        "require_evidence_value",
        lambda path, key, value: restore_bindings.append((path, key, value)),
    )
    monkeypatch.setattr(OPERATOR, "certify_standby", lambda value: {"subject": "ok"})
    monkeypatch.setattr(OPERATOR, "middleware_compose", lambda value: ["docker", "compose"])
    monkeypatch.setattr(OPERATOR, "validate_middleware_compose", lambda value, command: None)
    monkeypatch.setattr(OPERATOR, "middleware_runtime_image_matches", lambda value: [False, False, False])
    monkeypatch.setattr(
        OPERATOR,
        "snapshot_middleware_runtime",
        lambda value, backup_stamp: "20260830T200000Z",
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": "20260830T200000Z",
            "database_clients_running": (),
            "bundle_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "middleware_quiescence_stamp",
        lambda: "20260830T200000Z",
    )
    monkeypatch.setattr(
        OPERATOR,
        "resume_middleware_database_clients",
        lambda stamp, containers: None,
    )
    monkeypatch.setattr(OPERATOR, "wait_middleware_health", lambda: None)
    monkeypatch.setattr(
        OPERATOR,
        "verify_middleware_runtime",
        lambda value: {"middleware_runtime_digest": "PASS"},
    )

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"0056_klyrow_delivery_events (head)\n")

    monkeypatch.setattr(OPERATOR, "run_bytes", run)
    result = OPERATOR.rollout_middleware(config)
    assert evidence == [
        "stage",
        "stage-control-plane",
        "validate-backup",
        "restore-test",
    ]
    assert restore_bindings == [
        (Path("/restore-test.json"), "tested_backup_stamp", "20260830T180000Z"),
        (Path("/restore-test.json"), "isolated_middleware_migration", "PASS"),
        (
            Path("/restore-test.json"),
            "tested_middleware_database_head",
            "0056_klyrow_delivery_events",
        ),
    ]
    assert result["middleware_rollout"] == "PASS"
    assert result["middleware_database_head"] == "0056_klyrow_delivery_events"
    assert calls[0][-6:] == [
        "--rm",
        "--no-deps",
        "middleware-integration-api",
        "alembic",
        "upgrade",
        "head",
    ]
    recreate = next(command for command in calls if "--force-recreate" in command)
    assert "--no-deps" in recreate
    assert recreate[-3:] == list(OPERATOR.MIDDLEWARE_RUNTIME_SERVICES)


def test_middleware_rollout_failure_invokes_bounded_rollback(monkeypatch):
    config = OPERATOR.load_release_config()
    monkeypatch.setattr(OPERATOR, "require_action_evidence", lambda action, value: Path("/evidence"))
    monkeypatch.setattr(
        OPERATOR,
        "validate_backup_state",
        lambda: {"backup_stamp": "20260830T180000Z"},
    )
    monkeypatch.setattr(OPERATOR, "require_evidence_value", lambda path, key, value: None)
    monkeypatch.setattr(OPERATOR, "certify_standby", lambda value: {})
    monkeypatch.setattr(OPERATOR, "middleware_compose", lambda value: ["docker", "compose"])
    monkeypatch.setattr(OPERATOR, "validate_middleware_compose", lambda value, command: None)
    monkeypatch.setattr(OPERATOR, "middleware_runtime_image_matches", lambda value: [False, False, False])
    monkeypatch.setattr(
        OPERATOR,
        "snapshot_middleware_runtime",
        lambda value, backup_stamp: "20260830T200000Z",
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": "20260830T200000Z",
            "database_clients_running": (),
            "bundle_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "middleware_quiescence_stamp",
        lambda: "20260830T200000Z",
    )
    monkeypatch.setattr(
        OPERATOR,
        "run_bytes",
        lambda command, **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, command)),
    )
    rolled_back = []
    monkeypatch.setattr(OPERATOR, "rollback_middleware", lambda value: rolled_back.append(value) or {})
    with pytest.raises(subprocess.CalledProcessError):
        OPERATOR.rollout_middleware(config)
    assert rolled_back == [config]


def test_middleware_rollout_retry_preserves_original_rollback(monkeypatch):
    config = OPERATOR.load_release_config()
    monkeypatch.setattr(OPERATOR, "require_action_evidence", lambda action, value: Path("/evidence"))
    monkeypatch.setattr(
        OPERATOR,
        "validate_backup_state",
        lambda: {"backup_stamp": "20260830T180000Z"},
    )
    monkeypatch.setattr(OPERATOR, "require_evidence_value", lambda path, key, value: None)
    monkeypatch.setattr(OPERATOR, "certify_standby", lambda value: {})
    monkeypatch.setattr(OPERATOR, "middleware_compose", lambda value: ["docker", "compose"])
    monkeypatch.setattr(OPERATOR, "validate_middleware_compose", lambda value, command: None)
    monkeypatch.setattr(OPERATOR, "middleware_runtime_image_matches", lambda value: [True, True, True])
    snapshot_calls = []
    monkeypatch.setattr(
        OPERATOR,
        "snapshot_middleware_runtime",
        lambda value, backup_stamp: snapshot_calls.append((value, backup_stamp))
        or "20260830T190000Z",
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": "20260830T190000Z",
            "database_clients_running": (),
            "bundle_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "verify_middleware_runtime",
        lambda value: {"middleware_runtime_digest": "PASS"},
    )
    monkeypatch.setattr(
        OPERATOR,
        "middleware_database_revision",
        lambda: "0056_klyrow_delivery_events",
    )
    monkeypatch.setattr(OPERATOR, "middleware_quiescence_stamp", lambda: None)
    result = OPERATOR.rollout_middleware(config)
    assert snapshot_calls == [(config, "20260830T180000Z")]
    assert result["middleware_backup_stamp"] == "20260830T190000Z"
    assert result["middleware_already_current"] is True


def test_middleware_rollout_resumes_fresh_snapshot_before_health(monkeypatch):
    config = OPERATOR.load_release_config()
    stamp = "20260830T190000Z"
    marker = {"stamp": stamp}
    events = []
    monkeypatch.setattr(
        OPERATOR,
        "require_action_evidence",
        lambda action, value: Path("/evidence"),
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_backup_state",
        lambda: {"backup_stamp": "20260830T180000Z"},
    )
    monkeypatch.setattr(OPERATOR, "require_evidence_value", lambda path, key, value: None)
    monkeypatch.setattr(OPERATOR, "certify_standby", lambda value: {})
    monkeypatch.setattr(OPERATOR, "middleware_compose", lambda value: ["docker", "compose"])
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_compose",
        lambda value, command: None,
    )
    monkeypatch.setattr(
        OPERATOR,
        "middleware_runtime_image_matches",
        lambda value: [True, True, True],
    )
    monkeypatch.setattr(
        OPERATOR,
        "snapshot_middleware_runtime",
        lambda value, backup_stamp: events.append("snapshot") or stamp,
    )
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": stamp,
            "database_clients_running": ("codestra-middleware-integration-api-1",),
            "bundle_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "middleware_quiescence_stamp",
        lambda: marker["stamp"],
    )

    def resume(observed_stamp, containers):
        assert observed_stamp == stamp
        assert containers == ("codestra-middleware-integration-api-1",)
        events.append("resume")
        marker["stamp"] = None

    monkeypatch.setattr(OPERATOR, "resume_middleware_database_clients", resume)

    def wait_for_health():
        assert events == ["snapshot", "resume"]
        events.append("healthy")

    monkeypatch.setattr(OPERATOR, "wait_middleware_health", wait_for_health)

    def verify(value):
        assert events == ["snapshot", "resume", "healthy"]
        return {"middleware_runtime_digest": "PASS"}

    monkeypatch.setattr(OPERATOR, "verify_middleware_runtime", verify)
    monkeypatch.setattr(
        OPERATOR,
        "middleware_database_revision",
        lambda: "0056_klyrow_delivery_events",
    )
    result = OPERATOR.rollout_middleware(config)
    assert result["middleware_already_current"] is True
    assert marker["stamp"] is None


def test_compose_layers_are_copied_before_privileged_use(monkeypatch, tmp_path):
    _model_root_owned_test_files(monkeypatch)
    monkeypatch.setattr(
        OPERATOR.pwd,
        "getpwnam",
        lambda name: type("Account", (), {"pw_uid": os.getuid()})(),
    )
    source_a = tmp_path / "source-a.yaml"
    source_b = tmp_path / "source-b.yaml"
    source_a.write_text("services: {}\n")
    source_b.write_text("services: {worker: {}}\n")
    source_a.chmod(0o600)
    source_b.chmod(0o600)
    monkeypatch.setattr(
        OPERATOR,
        "MIDDLEWARE_COMPOSE_LAYERS",
        (
            (source_a, hashlib.sha256(source_a.read_bytes()).hexdigest()),
            (source_b, hashlib.sha256(source_b.read_bytes()).hexdigest()),
        ),
    )
    trusted_root = tmp_path / "trusted"
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_COMPOSE_RELEASE_ROOT", trusted_root)
    config = OPERATOR.load_release_config()
    trusted = OPERATOR.checked_middleware_compose_layers(config)
    copied = [path.read_bytes() for path in trusted]
    source_a.write_text("services: {attacker: {privileged: true}}\n")
    assert [path.read_bytes() for path in trusted] == copied
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in trusted)


def test_middleware_rollback_marker_is_published_atomically(monkeypatch, tmp_path):
    marker = tmp_path / "LAST_SUCCESS"
    replacements = []
    fsyncs = []
    real_replace = OPERATOR.os.replace
    real_fsync = OPERATOR.os.fsync

    def replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    def fsync(descriptor):
        fsyncs.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(OPERATOR.os, "replace", replace)
    monkeypatch.setattr(OPERATOR.os, "fsync", fsync)
    OPERATOR.atomic_root_text(marker, "20260830T190000Z\n", mode=0o600)

    assert marker.read_text() == "20260830T190000Z\n"
    assert marker.stat().st_mode & 0o777 == 0o600
    assert len(replacements) == 1
    assert replacements[0][1] == marker
    assert len(fsyncs) >= 2
    assert not list(tmp_path.glob(".LAST_SUCCESS.*.tmp"))
    snapshot_source = OPERATOR_PATH.read_text()
    assert "atomic_root_text(MIDDLEWARE_ROLLBACK_MARKER, stamp + \"\\n\", mode=0o600)" in snapshot_source


def test_middleware_snapshot_flushes_bundle_before_marker(monkeypatch, tmp_path):
    root = tmp_path / "middleware-backups"
    root.mkdir(mode=0o755)
    marker = root / "LAST_SUCCESS"
    quiesce_marker = root / "QUIESCED"
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_BACKUP_ROOT", root)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_ROLLBACK_MARKER", marker)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_QUIESCE_MARKER", quiesce_marker)
    image_ids = {
        container: "sha256:" + str(index) * 64
        for index, container in enumerate(OPERATOR.MIDDLEWARE_RUNTIME_CONTAINERS, 1)
    }
    client_state = {
        container: True for container in OPERATOR.MIDDLEWARE_DATABASE_CLIENT_CONTAINERS
    }

    def inspect(container):
        value = {"State": {"Running": client_state[container]}}
        if container in image_ids:
            value["Image"] = image_ids[container]
        return value

    monkeypatch.setattr(OPERATOR, "docker_inspect", inspect)
    monkeypatch.setattr(OPERATOR, "middleware_database_revision", lambda: "0054_previous")

    def run(command, **kwargs):
        statement = command[-1] if command else ""
        if command[1:3] == ["ps", "--all"]:
            return subprocess.CompletedProcess(
                command,
                0,
                ("\n".join(OPERATOR.MIDDLEWARE_DATABASE_CLIENT_CONTAINERS) + "\n").encode(),
            )
        if command[1:3] == ["stop", "--time"]:
            for container in command[4:]:
                client_state[container] = False
        if command[1] == "start":
            for container in command[2:]:
                client_state[container] = True
        if "datallowconn" in statement:
            return subprocess.CompletedProcess(command, 0, b"true\n")
        if "datconnlimit" in statement:
            return subprocess.CompletedProcess(command, 0, b"-1\n")
        if "pg_get_userbyid" in statement:
            return subprocess.CompletedProcess(command, 0, b"middleware_data_owner\n")
        if "exists(select 1 from pg_database" in statement:
            return subprocess.CompletedProcess(command, 0, b"true\n")
        if "select count(*) from pg_stat_activity" in statement:
            return subprocess.CompletedProcess(command, 0, b"0\n")
        return subprocess.CompletedProcess(command, 0, b"")

    monkeypatch.setattr(OPERATOR, "run_bytes", run)
    database_dump = b"pre-change-dump"

    def stream_dump(command, path, **kwargs):
        assert "pg_dump" in command
        OPERATOR.atomic_root_bytes(path, database_dump, mode=0o600)
        return hashlib.sha256(database_dump).hexdigest(), len(database_dump)

    monkeypatch.setattr(OPERATOR, "stream_command_to_atomic_file", stream_dump)
    events = []
    real_replace = OPERATOR.os.replace
    real_fsync_directory = OPERATOR.fsync_directory

    def replace(source, destination):
        events.append(("replace", Path(destination)))
        real_replace(source, destination)

    def fsync_directory(path):
        events.append(("fsync-directory", Path(path)))
        real_fsync_directory(path)

    monkeypatch.setattr(OPERATOR.os, "replace", replace)
    monkeypatch.setattr(OPERATOR, "fsync_directory", fsync_directory)
    stamp = OPERATOR.snapshot_middleware_runtime(
        OPERATOR.load_release_config(),
        "20260830T180000Z",
    )
    backup = root / stamp
    expected_members = {
        *(f"{service}.image-id" for service in OPERATOR.MIDDLEWARE_RUNTIME_SERVICES),
        "database-owner",
        "database-allows-connections",
        "database-connection-limit",
        "database-head",
        "database-clients-running.json",
        "readiness-backup-stamp",
        "middleware.dump",
        "middleware.dump.sha256",
        "rollback.override.yaml",
        "rollout-target.json",
    }

    assert marker.read_text().strip() == stamp
    assert quiesce_marker.read_text().strip() == stamp
    assert json.loads((backup / "database-clients-running.json").read_text()) == {
        "containers": list(OPERATOR.MIDDLEWARE_DATABASE_CLIENT_CONTAINERS)
    }
    assert not any(client_state.values())
    assert expected_members <= {path.name for path in backup.iterdir()}
    assert all((backup / name).stat().st_mode & 0o777 == 0o600 for name in expected_members)
    marker_index = events.index(("replace", marker))
    assert ("fsync-directory", backup) in events[:marker_index]
    assert all(events.index(("replace", backup / name)) < marker_index for name in expected_members)


def test_middleware_database_clients_quiesce_and_resume_exact_prior_set(
    monkeypatch, tmp_path
):
    _model_root_owned_test_files(monkeypatch)
    root = tmp_path / "middleware-backups"
    root.mkdir(mode=0o700)
    marker = root / "QUIESCED"
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_BACKUP_ROOT", root)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_QUIESCE_MARKER", marker)
    originally_running = tuple(OPERATOR.MIDDLEWARE_DATABASE_CLIENT_CONTAINERS[::2])
    state = {
        container: container in originally_running
        for container in OPERATOR.MIDDLEWARE_DATABASE_CLIENT_CONTAINERS
    }
    monkeypatch.setattr(
        OPERATOR,
        "docker_inspect",
        lambda container: {"State": {"Running": state[container]}},
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["ps", "--all"]:
            return subprocess.CompletedProcess(
                command,
                0,
                ("\n".join(OPERATOR.MIDDLEWARE_DATABASE_CLIENT_CONTAINERS) + "\n").encode(),
            )
        if command[1] == "stop":
            for container in command[4:]:
                state[container] = False
        elif command[1] == "start":
            for container in command[2:]:
                state[container] = True
        return subprocess.CompletedProcess(command, 0, b"")

    monkeypatch.setattr(OPERATOR, "run_bytes", run)
    waited = []
    monkeypatch.setattr(
        OPERATOR,
        "wait_middleware_database_clients",
        lambda containers: waited.append(containers),
    )
    stamp = "20260830T200000Z"

    assert OPERATOR.quiesce_middleware_database_clients(stamp) == originally_running
    assert marker.read_text().strip() == stamp
    assert not any(state.values())

    OPERATOR.resume_middleware_database_clients(stamp, originally_running)

    assert not marker.exists()
    assert tuple(container for container, running in state.items() if running) == originally_running
    stop = next(command for command in calls if command[1] == "stop")
    start = next(command for command in calls if command[1] == "start")
    assert stop[4:] == list(originally_running)
    assert start[2:] == list(originally_running)
    assert waited == [originally_running]


def test_middleware_database_client_wait_rejects_resumed_worker_exit(monkeypatch):
    container = "codestra-middleware-sync-worker-1"
    observations = iter(
        (
            {
                "RestartCount": 0,
                "State": {"Running": True, "StartedAt": "2026-09-05T11:00:00Z"},
            },
            {
                "RestartCount": 0,
                "State": {"Running": False, "StartedAt": "2026-09-05T11:00:00Z"},
            },
        )
    )
    monkeypatch.setattr(OPERATOR, "docker_inspect", lambda value: next(observations))
    monkeypatch.setattr(OPERATOR.time, "sleep", lambda seconds: None)

    with pytest.raises(OPERATOR.OperatorError, match="did not remain running"):
        OPERATOR.wait_middleware_database_clients((container,))


def test_middleware_database_client_wait_restarts_stability_window(monkeypatch):
    container = "codestra-middleware-reconciliation-worker-1"
    observations = iter(
        (
            {
                "RestartCount": 0,
                "State": {"Running": True, "StartedAt": "2026-09-05T11:00:00Z"},
            },
            {
                "RestartCount": 1,
                "State": {"Running": True, "StartedAt": "2026-09-05T11:00:02Z"},
            },
        )
    )
    clock = iter((0.0, 0.0, 0.5, 2.0))
    monkeypatch.setattr(OPERATOR, "docker_inspect", lambda value: next(observations))
    monkeypatch.setattr(OPERATOR.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(OPERATOR.time, "sleep", lambda seconds: None)

    with pytest.raises(OPERATOR.OperatorError, match="health check timed out"):
        OPERATOR.wait_middleware_database_clients((container,), timeout_seconds=1)


def test_middleware_database_client_inventory_rejects_an_unclassified_service(
    monkeypatch,
):
    monkeypatch.setattr(
        OPERATOR,
        "run_bytes",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            b"codestra-middleware-unreviewed-writer-1\n",
        ),
    )

    with pytest.raises(OPERATOR.OperatorError, match="requires review"):
        OPERATOR.middleware_database_client_state()


def test_middleware_database_client_inventory_includes_every_scaled_replica(
    monkeypatch,
):
    containers = (
        "codestra-middleware-sync-worker-1",
        "codestra-middleware-sync-worker-2",
        "codestra-middleware-sync-worker-10",
    )
    monkeypatch.setattr(
        OPERATOR,
        "run_bytes",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            ("\n".join(containers) + "\n").encode(),
        ),
    )
    monkeypatch.setattr(
        OPERATOR,
        "docker_inspect",
        lambda container: {"State": {"Running": True}},
    )

    assert tuple(OPERATOR.middleware_database_client_state()) == containers
    assert OPERATOR.middleware_database_client_canonical(containers[1]) == (
        "codestra-middleware-sync-worker-1"
    )
    OPERATOR.validate_middleware_database_client_names(containers)


def test_middleware_database_client_bundle_validation_rejects_bad_replica_sets():
    with pytest.raises(OPERATOR.OperatorError, match="client set is malformed"):
        OPERATOR.validate_middleware_database_client_names(
            (
                "codestra-middleware-sync-worker-2",
                "codestra-middleware-sync-worker-2",
            )
        )
    with pytest.raises(OPERATOR.OperatorError, match="client set is malformed"):
        OPERATOR.validate_middleware_database_client_names(
            ("codestra-middleware-unreviewed-writer-2",)
        )


def test_completed_rollback_forces_fresh_snapshot(monkeypatch, tmp_path):
    _model_root_owned_test_files(monkeypatch)
    config = OPERATOR.load_release_config()
    stamp = "20260830T190000Z"
    backup = tmp_path / stamp
    backup.mkdir(mode=0o700)
    marker = tmp_path / "LAST_SUCCESS"
    marker.write_text(stamp + "\n")
    marker.chmod(0o600)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_ROLLBACK_MARKER", marker)
    monkeypatch.setattr(OPERATOR, "middleware_rollback_target", lambda value: config)
    bundle = {"stamp": stamp}
    monkeypatch.setattr(OPERATOR, "validate_middleware_rollback", lambda value: bundle)
    monkeypatch.setattr(
        OPERATOR,
        "middleware_rollback_progress",
        lambda value: {
            "phase": "COMPLETE",
            "failed_state": "failed-state-20260830T190001Z-1.dump",
            "failed_state_sha256": "1" * 64,
        },
    )
    verified = []
    monkeypatch.setattr(
        OPERATOR,
        "verify_middleware_rollback_readback",
        lambda value: verified.append(value) or "0054_previous",
    )

    assert OPERATOR.reusable_middleware_snapshot(config) is None
    assert verified == [bundle]


def test_incomplete_attempt_reuses_original_snapshot(monkeypatch, tmp_path):
    _model_root_owned_test_files(monkeypatch)
    config = OPERATOR.load_release_config()
    stamp = "20260830T190000Z"
    backup = tmp_path / stamp
    backup.mkdir(mode=0o700)
    marker = tmp_path / "LAST_SUCCESS"
    marker.write_text(stamp + "\n")
    marker.chmod(0o600)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_ROLLBACK_MARKER", marker)
    monkeypatch.setattr(OPERATOR, "middleware_rollback_target", lambda value: config)
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {"stamp": stamp},
    )
    monkeypatch.setattr(OPERATOR, "middleware_rollback_progress", lambda value: None)

    assert OPERATOR.reusable_middleware_snapshot(config) == stamp


def test_database_dump_streams_to_disk_and_hashes_incrementally(tmp_path):
    target = tmp_path / "database.dump"
    size = 3 * 1024 * 1024
    command = [
        sys.executable,
        "-c",
        f"import sys; sys.stdout.buffer.write(b'x' * {size})",
    ]

    digest, written = OPERATOR.stream_command_to_atomic_file(command, target)

    assert written == size
    assert digest == hashlib.sha256(b"x" * size).hexdigest()
    assert target.stat().st_mode & 0o777 == 0o600
    assert OPERATOR.hash_operator_file(target) == (digest, size)


def test_middleware_rollback_restores_database_and_reads_back_images(monkeypatch, tmp_path):
    config = OPERATOR.load_release_config()
    stamp = "20260830T190000Z"
    backup = tmp_path / stamp
    backup.mkdir(mode=0o700)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(
        OPERATOR, "quiesce_middleware_database_clients", lambda value: ()
    )
    monkeypatch.setattr(
        OPERATOR,
        "resume_middleware_database_clients",
        lambda stamp, containers: None,
    )
    database_dump_path = backup / "middleware.dump"
    database_dump_digest = hashlib.sha256(b"pre-change-dump").hexdigest()
    image_ids = {
        service: "sha256:" + str(index) * 64
        for index, service in enumerate(OPERATOR.MIDDLEWARE_RUNTIME_SERVICES, 1)
    }
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": stamp,
            "override": Path("/rollback.override.yaml"),
            "image_ids": image_ids,
            "database_owner": "middleware_data_owner",
            "database_allows_connections": "true",
            "database_connection_limit": "-1",
            "database_head": "0054_previous",
            "database_dump_path": database_dump_path,
            "database_dump_sha256": database_dump_digest,
            "readiness_backup_stamp": "20260830T180000Z",
            "database_clients_running": (),
        },
    )
    monkeypatch.setattr(OPERATOR, "middleware_compose", lambda value, rollback_override: ["docker", "compose"])
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if any("select count(*) from pg_stat_activity" in part for part in command):
            return subprocess.CompletedProcess(command, 0, b"0\n")
        return subprocess.CompletedProcess(command, 0, b"")

    monkeypatch.setattr(OPERATOR, "run_bytes", run)
    failed_dump = b"failed-state-dump"

    def stream_dump(command, path, **kwargs):
        calls.append((command, {"stream_path": path}))
        OPERATOR.atomic_root_bytes(path, failed_dump, mode=0o600)
        return hashlib.sha256(failed_dump).hexdigest(), len(failed_dump)

    def restore(command, path, digest, **kwargs):
        calls.append((command, {"stdin_path": path, "stdin_sha256": digest}))
        return subprocess.CompletedProcess(command, 0, b"")

    monkeypatch.setattr(OPERATOR, "stream_command_to_atomic_file", stream_dump)
    monkeypatch.setattr(OPERATOR, "run_with_verified_file_stdin", restore)
    monkeypatch.setattr(OPERATOR, "middleware_database_exists", lambda: True)
    monkeypatch.setattr(OPERATOR, "wait_middleware_health", lambda: None)
    monkeypatch.setattr(OPERATOR, "middleware_database_revision", lambda: "0054_previous")

    def inspect(container):
        service = next(
            service
            for service, expected_container in OPERATOR.MIDDLEWARE_RUNTIME_SERVICES.items()
            if expected_container == container
        )
        environment = [f"{name}=false" for name in OPERATOR.MIDDLEWARE_REQUIRED_FALSE_FLAGS]
        return {"Image": image_ids[service], "Config": {"Env": environment}}

    monkeypatch.setattr(OPERATOR, "docker_inspect", inspect)
    result = OPERATOR.rollback_middleware(config)
    assert result["middleware_rollback"] == "PASS"
    assert result["middleware_database_head"] == "0054_previous"
    commands = [command for command, _ in calls]
    failed_dump_index = next(index for index, command in enumerate(commands) if "pg_dump" in command)
    restore_index = next(index for index, command in enumerate(commands) if "pg_restore" in command)
    start_index = next(index for index, command in enumerate(commands) if "--force-recreate" in command)
    writer_fence_index = next(
        index
        for index, command in enumerate(commands)
        if any("alter database codestra_middleware with connection limit 0" in part for part in command)
    )
    destructive_fence_index = next(
        index
        for index, command in enumerate(commands)
        if any("allow_connections false" in part for part in command)
    )
    terminate_index = next(
        index
        for index, command in enumerate(commands)
        if any("pg_terminate_backend" in part for part in command)
    )
    create_index = next(
        index
        for index, command in enumerate(commands)
        if any("create database" in part for part in command)
    )
    limit_restore_index = next(
        index
        for index, command in enumerate(commands)
        if any("connection limit -1" in part for part in command)
    )
    connection_restore_index = next(
        index
        for index, command in enumerate(commands)
        if any("allow_connections true" in part for part in command)
    )
    assert writer_fence_index < terminate_index < failed_dump_index
    assert failed_dump_index < destructive_fence_index < create_index < restore_index
    assert any("connection limit 0" in part for part in commands[create_index])
    assert restore_index < limit_restore_index < connection_restore_index < start_index
    assert restore_index < start_index
    assert calls[restore_index][1]["stdin_path"] == database_dump_path
    assert calls[restore_index][1]["stdin_sha256"] == database_dump_digest
    assert (backup / result["failed_state_preserved"]).read_bytes() == b"failed-state-dump"


def test_middleware_rollback_resumes_after_database_drop(monkeypatch, tmp_path):
    config = OPERATOR.load_release_config()
    stamp = "20260830T191500Z"
    backup = tmp_path / stamp
    backup.mkdir(mode=0o700)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(
        OPERATOR, "quiesce_middleware_database_clients", lambda value: ()
    )
    monkeypatch.setattr(
        OPERATOR,
        "resume_middleware_database_clients",
        lambda stamp, containers: None,
    )
    database_dump_path = backup / "middleware.dump"
    database_dump_digest = hashlib.sha256(b"pre-change-dump").hexdigest()
    image_ids = {
        service: "sha256:" + str(index) * 64
        for index, service in enumerate(OPERATOR.MIDDLEWARE_RUNTIME_SERVICES, 1)
    }
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": stamp,
            "override": Path("/rollback.override.yaml"),
            "image_ids": image_ids,
            "database_owner": "middleware_data_owner",
            "database_allows_connections": "true",
            "database_connection_limit": "-1",
            "database_head": "0054_previous",
            "database_dump_path": database_dump_path,
            "database_dump_sha256": database_dump_digest,
            "readiness_backup_stamp": "20260830T180000Z",
            "database_clients_running": (),
        },
    )
    monkeypatch.setattr(
        OPERATOR,
        "middleware_compose",
        lambda value, rollback_override: ["docker", "compose"],
    )
    calls = []
    fail_create_once = True
    database_present = True
    existence_checks = []

    def run(command, **kwargs):
        nonlocal fail_create_once, database_present
        calls.append((command, kwargs))
        if "dropdb" in command:
            database_present = False
        if any("create database" in part for part in command) and fail_create_once:
            fail_create_once = False
            raise subprocess.CalledProcessError(1, command)
        if any("create database" in part for part in command):
            database_present = True
        if any("select count(*) from pg_stat_activity" in part for part in command):
            return subprocess.CompletedProcess(command, 0, b"0\n")
        return subprocess.CompletedProcess(command, 0, b"")

    monkeypatch.setattr(OPERATOR, "run_bytes", run)
    failed_dump = b"failed-state-dump"

    def stream_dump(command, path, **kwargs):
        calls.append((command, {"stream_path": path}))
        OPERATOR.atomic_root_bytes(path, failed_dump, mode=0o600)
        return hashlib.sha256(failed_dump).hexdigest(), len(failed_dump)

    def restore(command, path, digest, **kwargs):
        calls.append((command, {"stdin_path": path, "stdin_sha256": digest}))
        return subprocess.CompletedProcess(command, 0, b"")

    monkeypatch.setattr(OPERATOR, "stream_command_to_atomic_file", stream_dump)
    monkeypatch.setattr(OPERATOR, "run_with_verified_file_stdin", restore)

    def database_exists():
        existence_checks.append(database_present)
        return database_present

    monkeypatch.setattr(OPERATOR, "middleware_database_exists", database_exists)
    monkeypatch.setattr(OPERATOR, "wait_middleware_health", lambda: None)
    monkeypatch.setattr(OPERATOR, "middleware_database_revision", lambda: "0054_previous")

    def inspect(container):
        service = next(
            service
            for service, expected_container in OPERATOR.MIDDLEWARE_RUNTIME_SERVICES.items()
            if expected_container == container
        )
        environment = [f"{name}=false" for name in OPERATOR.MIDDLEWARE_REQUIRED_FALSE_FLAGS]
        return {"Image": image_ids[service], "Config": {"Env": environment}}

    monkeypatch.setattr(OPERATOR, "docker_inspect", inspect)

    with pytest.raises(subprocess.CalledProcessError):
        OPERATOR.rollback_middleware(config)
    progress = OPERATOR.middleware_rollback_progress(backup)
    assert progress is not None
    assert progress["phase"] == "FAILED_STATE_PRESERVED"
    with pytest.raises(OPERATOR.OperatorError, match="rollback is incomplete"):
        OPERATOR.prepare_middleware_rollout(stamp)

    result = OPERATOR.rollback_middleware(config)
    assert result["middleware_rollback"] == "PASS"
    assert sum("pg_dump" in command for command, _ in calls) == 1
    assert sum("dropdb" in command for command, _ in calls) == 2
    assert existence_checks == [True, False]
    assert sum(
        any("allow_connections false" in part for part in command)
        for command, _ in calls
    ) == 1
    complete = OPERATOR.middleware_rollback_progress(backup)
    assert complete is not None
    assert complete["phase"] == "COMPLETE"

    call_count = len(calls)
    repeated = OPERATOR.rollback_middleware(config)
    assert repeated["middleware_rollback_already_complete"] is True
    assert len(calls) == call_count


def test_middleware_rollback_checkpoints_restored_database_while_still_fenced(
    monkeypatch, tmp_path
):
    config = OPERATOR.load_release_config()
    stamp = "20260830T191600Z"
    backup = tmp_path / stamp
    backup.mkdir(mode=0o700)
    failed_state = "failed-state-20260830T191601Z-1.dump"
    failed_digest = "1" * 64
    progress = {
        "phase": "FAILED_STATE_PRESERVED",
        "failed_state": failed_state,
        "failed_state_sha256": failed_digest,
    }
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": stamp,
            "override": Path("/rollback.override.yaml"),
            "image_ids": {},
            "database_owner": "middleware_data_owner",
            "database_allows_connections": "true",
            "database_connection_limit": "-1",
            "database_head": "0054_previous",
            "database_clients_running": (),
            "database_dump_path": backup / "middleware.dump",
            "database_dump_sha256": "2" * 64,
            "readiness_backup_stamp": "20260830T180000Z",
        },
    )
    monkeypatch.setattr(OPERATOR, "middleware_rollback_progress", lambda value: progress)
    monkeypatch.setattr(OPERATOR, "quiesce_middleware_database_clients", lambda value: ())
    monkeypatch.setattr(
        OPERATOR,
        "middleware_compose",
        lambda value, rollback_override: ["docker", "compose"],
    )
    monkeypatch.setattr(OPERATOR, "fence_middleware_database_clients", lambda: True)
    events = []
    monkeypatch.setattr(
        OPERATOR,
        "run_bytes",
        lambda command, **kwargs: events.append(("command", command))
        or subprocess.CompletedProcess(command, 0, b""),
    )
    monkeypatch.setattr(
        OPERATOR,
        "run_with_verified_file_stdin",
        lambda command, path, digest, **kwargs: events.append(("restore", command))
        or subprocess.CompletedProcess(command, 0, b""),
    )
    monkeypatch.setattr(
        OPERATOR,
        "set_middleware_database_connection_limit",
        lambda value: events.append(("policy-restored", value)),
    )

    def checkpoint(path, phase, name, digest):
        events.append(("checkpoint", phase))
        if phase == "DATABASE_RESTORED_FENCED":
            raise RuntimeError("simulated interruption after durable checkpoint")
        return {"phase": phase, "failed_state": name, "failed_state_sha256": digest}

    monkeypatch.setattr(OPERATOR, "record_middleware_rollback_progress", checkpoint)

    with pytest.raises(RuntimeError, match="durable checkpoint"):
        OPERATOR.rollback_middleware(config)

    assert ("checkpoint", "DATABASE_RESTORED_FENCED") in events
    assert not any(event[0] == "policy-restored" for event in events)


@pytest.mark.parametrize(("output", "expected"), [(b"true\n", True), (b"false\n", False)])
def test_middleware_database_existence_readback(monkeypatch, output, expected):
    monkeypatch.setattr(
        OPERATOR,
        "run_bytes",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, output),
    )

    assert OPERATOR.middleware_database_exists() is expected


def test_middleware_database_existence_rejects_unknown_output(monkeypatch):
    monkeypatch.setattr(
        OPERATOR,
        "run_bytes",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, b""),
    )

    with pytest.raises(OPERATOR.OperatorError, match="existence readback failed"):
        OPERATOR.middleware_database_exists()


def test_middleware_rollback_rejects_wrong_restored_image(monkeypatch, tmp_path):
    config = OPERATOR.load_release_config()
    stamp = "20260830T190000Z"
    backup = tmp_path / stamp
    backup.mkdir(mode=0o700)
    monkeypatch.setattr(OPERATOR, "MIDDLEWARE_BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(
        OPERATOR, "quiesce_middleware_database_clients", lambda value: ()
    )
    monkeypatch.setattr(
        OPERATOR,
        "resume_middleware_database_clients",
        lambda stamp, containers: None,
    )
    database_dump_path = backup / "middleware.dump"
    database_dump_digest = hashlib.sha256(b"pre-change-dump").hexdigest()
    image_ids = {service: "sha256:" + "1" * 64 for service in OPERATOR.MIDDLEWARE_RUNTIME_SERVICES}
    monkeypatch.setattr(
        OPERATOR,
        "validate_middleware_rollback",
        lambda value: {
            "stamp": stamp,
            "override": Path("/rollback.override.yaml"),
            "image_ids": image_ids,
            "database_owner": "middleware_data_owner",
            "database_allows_connections": "true",
            "database_connection_limit": "-1",
            "database_head": "0054_previous",
            "database_dump_path": database_dump_path,
            "database_dump_sha256": database_dump_digest,
            "readiness_backup_stamp": "20260830T180000Z",
            "database_clients_running": (),
        },
    )
    monkeypatch.setattr(OPERATOR, "middleware_compose", lambda value, rollback_override: ["docker", "compose"])
    monkeypatch.setattr(
        OPERATOR,
        "run_bytes",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, b""),
    )
    failed_dump = b"failed-state-dump"

    def stream_dump(command, path, **kwargs):
        OPERATOR.atomic_root_bytes(path, failed_dump, mode=0o600)
        return hashlib.sha256(failed_dump).hexdigest(), len(failed_dump)

    monkeypatch.setattr(OPERATOR, "stream_command_to_atomic_file", stream_dump)
    monkeypatch.setattr(
        OPERATOR,
        "run_with_verified_file_stdin",
        lambda command, path, digest, **kwargs: subprocess.CompletedProcess(command, 0, b""),
    )
    monkeypatch.setattr(OPERATOR, "middleware_database_exists", lambda: True)
    monkeypatch.setattr(OPERATOR, "fence_middleware_database_clients", lambda: True)
    monkeypatch.setattr(OPERATOR, "wait_middleware_health", lambda: None)
    monkeypatch.setattr(
        OPERATOR,
        "docker_inspect",
        lambda container: {"Image": "sha256:" + "2" * 64, "Config": {"Env": []}},
    )
    with pytest.raises(OPERATOR.OperatorError, match="image readback mismatch"):
        OPERATOR.rollback_middleware(config)


def test_web_traffic_pointer_never_enables_customer_channels(monkeypatch):
    monkeypatch.setattr(OPERATOR, "core_web_health", lambda config: {"core_web_dependencies": "PASS"})
    gates = []
    monkeypatch.setattr(OPERATOR, "kong_traffic_gate", lambda enabled: gates.append(enabled))
    monkeypatch.setattr(OPERATOR, "probe_core_web", lambda expected: None)
    written = {}
    monkeypatch.setattr(OPERATOR, "atomic_root_json", lambda path, value: written.update(value))
    result = OPERATOR.set_core_web_traffic(OPERATOR.load_release_config(), True)
    assert result["core_web_api_traffic"] == "ENABLED"
    assert written["customer_wide_email"] is False
    assert written["sms_production"] is False
    assert written["voice_production"] is False
    assert written["pstn_dialing"] is False
    assert gates == [False]


def test_core_web_health_rejects_running_without_healthcheck(monkeypatch):
    config = OPERATOR.load_release_config()
    monkeypatch.setattr(OPERATOR, "load_pointer", lambda path: {
        "protected_sha": config["protected_sha"], "image_digest": config["image_digest"]
    })
    monkeypatch.setattr(OPERATOR, "validate_control_plane", lambda value: {})
    monkeypatch.setattr(OPERATOR, "verify_middleware_runtime", lambda value: {})
    monkeypatch.setattr(OPERATOR, "docker_inspect", lambda name: {
        "State": {"Running": True, "Health": {}}
    })
    with pytest.raises(OPERATOR.OperatorError, match="dependency unhealthy"):
        OPERATOR.core_web_health(config)


def test_core_web_health_requires_auth_and_caddy_readiness(monkeypatch):
    config = OPERATOR.load_release_config()
    monkeypatch.setattr(OPERATOR, "load_pointer", lambda path: {
        "protected_sha": config["protected_sha"], "image_digest": config["image_digest"]
    })
    monkeypatch.setattr(OPERATOR, "validate_control_plane", lambda value: {})
    monkeypatch.setattr(OPERATOR, "verify_middleware_runtime", lambda value: {})
    monkeypatch.setattr(OPERATOR, "docker_inspect", lambda name: {
        "State": {"Running": True, "Health": {"Status": "healthy"}}
    })
    calls = []
    monkeypatch.setattr(OPERATOR, "probe_auth_gateway", lambda: calls.append("auth"))
    monkeypatch.setattr(OPERATOR, "probe_core_web", lambda expected: calls.append(expected))
    result = OPERATOR.core_web_health(config)
    assert calls == ["auth", {401, 503}]
    assert result["auth_gateway_readiness"] == "PASS"
    assert result["caddy_serving_path"] == "PASS"


def test_auth_gateway_probe_rejects_non_private_address(monkeypatch):
    monkeypatch.setattr(OPERATOR, "docker_inspect", lambda name: {
        "State": {"Running": True},
        "NetworkSettings": {"Networks": {
            OPERATOR.AUTH_GATEWAY_NETWORK: {"IPAddress": "203.0.113.10"}
        }},
    })
    with pytest.raises(OPERATOR.OperatorError, match="not private"):
        OPERATOR.probe_auth_gateway()


def test_worker_healthcheck_is_not_disabled():
    compose = (ROOT / "deploy/control-plane/compose.yaml").read_text(encoding="utf-8")
    worker = compose.split("  worker:\n", 1)[1]
    assert "disable: true" not in worker
    assert "control-plane-worker-heartbeat" in worker


def test_activation_rejects_incomplete_rollback_bundle(monkeypatch):
    monkeypatch.setattr(
        OPERATOR,
        "checked_root_file",
        lambda path, expected_mode=0o600: (
            "codestra_control_plane" if path.name == "database-owner" else "20260823T000000Z"
        ),
    )
    backup = OPERATOR.CONTROL_PLANE_BACKUP_ROOT / "20260823T000000Z"
    monkeypatch.setattr(OPERATOR.Path, "lstat", lambda self: type("S", (), {
        "st_mode": 0o40700, "st_uid": 0, "st_gid": 0
    })())
    monkeypatch.setattr(OPERATOR.Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(OPERATOR, "checked_root_bytes", lambda path: b"")
    with pytest.raises(OPERATOR.OperatorError, match="dump is empty"):
        OPERATOR.validate_control_plane_rollback()


def test_rollback_bundle_rejects_changed_dump(monkeypatch):
    monkeypatch.setattr(
        OPERATOR,
        "checked_root_file",
        lambda path, expected_mode=0o600: {
            "LAST_SUCCESS": "20260823T000000Z",
            "database-owner": "codestra_control_plane",
            "control-plane.sql.sha256": "0" * 64,
            "api-image-id": "sha256:" + "1" * 64,
            "worker-image-id": "sha256:" + "2" * 64,
        }[path.name],
    )
    monkeypatch.setattr(OPERATOR.Path, "lstat", lambda self: type("S", (), {
        "st_mode": 0o40700, "st_uid": 0, "st_gid": 0
    })())
    monkeypatch.setattr(OPERATOR.Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(OPERATOR, "checked_root_bytes", lambda path: b"valid-prefix-truncated")
    with pytest.raises(OPERATOR.OperatorError, match="checksum mismatch"):
        OPERATOR.validate_control_plane_rollback()


def test_middleware_runtime_requires_false_delivery_flags(monkeypatch):
    config = OPERATOR.load_release_config()
    safe = [f"{name}=false" for name in OPERATOR.MIDDLEWARE_REQUIRED_FALSE_FLAGS]
    monkeypatch.setattr(OPERATOR, "docker_inspect", lambda name: {
        "Config": {
            "Image": f"{OPERATOR.MIDDLEWARE_IMAGE}@{config['image_digest']}",
            "Env": [*safe, "CALLBACK_DELIVERY_ENABLED=true"],
        },
        "State": {"Health": {"Status": "healthy"}},
    })
    with pytest.raises(OPERATOR.OperatorError, match="delivery flag unsafe"):
        OPERATOR.verify_middleware_runtime(config)


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


@pytest.mark.parametrize("action", ["status", "collect-evidence", "kong-readback"])
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
    monkeypatch.setattr(
        OPERATOR,
        "kong_runtime_readback",
        lambda: {"route_count": 29, "core_web_traffic_gate_present": True},
    )
    code, result = OPERATOR.execute(action)
    assert code == 0
    if action == "kong-readback":
        assert result["route_count"] == 29
        assert result["core_web_traffic_gate_present"] is True
    else:
        assert result["returncode"] == 0


def test_kong_runtime_readback_is_sanitized_and_reports_traffic_gate(monkeypatch) -> None:
    responses = {
        "/routes?size=1000": {"data": [{"id": "r1", "name": "health",
            "service": {"id": "s1"}, "protocols": ["https"], "methods": ["GET"],
            "hosts": ["api.example.invalid"], "paths": ["/health"],
            "headers": {"x-api-key": ["secret"]}}]},
        "/services?size=1000": {"data": [{"id": "s1", "name": "api",
            "protocol": "http", "host": "middleware", "port": 8000, "path": "/",
            "retries": 2, "connect_timeout": 1000, "read_timeout": 2000,
            "write_timeout": 2000, "enabled": True,
            "client_certificate": {"id": "private"}}]},
        "/upstreams?size=1000": {"data": [{"id": "u1", "name": "middleware",
            "algorithm": "round-robin"}]},
        "/upstreams/u1/health": {"data": [{"id": "t1",
            "target": "10.0.0.10:8000", "weight": 100, "health": "HEALTHY",
            "certificate": "secret"}]},
        "/plugins?size=1000": {"data": [{"id": "p1",
            "name": "request-termination",
            "instance_name": OPERATOR.KONG_TRAFFIC_GATE_INSTANCE, "enabled": True,
            "route": None, "service": None, "consumer": None,
            "config": {"message": "secret"}}]},
    }
    monkeypatch.setattr(OPERATOR, "kong_json", lambda method, path: responses[path])
    result = OPERATOR.kong_runtime_readback()
    assert result["route_count"] == 1
    assert result["core_web_traffic_gate_present"] is True
    serialized = json.dumps(result)
    assert "x-api-key" not in serialized
    assert "client_certificate" not in serialized
    assert "certificate" not in serialized
    assert '"config"' not in serialized
    assert len(result["sanitized_configuration_sha256"]) == 64


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


def test_middleware_rollback_skips_fallible_safety_probes(monkeypatch) -> None:
    monkeypatch.setattr(
        OPERATOR,
        "safety_state",
        lambda: pytest.fail("recovery must not call remote safety probes"),
    )
    monkeypatch.setattr(
        OPERATOR,
        "rollback_middleware",
        lambda _config: {"middleware_rollback": "PASS"},
    )

    code, result = OPERATOR.execute("rollback-middleware")

    assert code == 0
    assert result["middleware_rollback"] == "PASS"
    assert result["safety"]["probe_status"] == "SKIPPED_FOR_RECOVERY"


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
    for relative in (
        "../../PRODUCTION-DATABASE-MANIFEST.yaml",
        "../../tools/validate_production_database_manifest.py",
    ):
        digest = subprocess.check_output(
            ["sha256sum", str(PACKAGE / relative)], text=True
        ).split()[0]
        assert f"{digest}  {relative}" in installer
    restore = ROOT / "operations" / "readiness" / "codestra-isolated-restore-rehearsal.sh"
    restore_digest = subprocess.check_output(["sha256sum", str(restore)], text=True).split()[0]
    assert restore_digest in installer
    assert 'restore_source=$script_dir/../readiness/codestra-isolated-restore-rehearsal.sh' in installer

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
    for action in EXPECTED_ACTIONS:
        assert f'"{action}"' in text
    assert 'path = "/etc/codestra/production-operator/release.json"' in text
    assert "parts[1:] != expected" in text
    assert 'exec /usr/bin/sudo -n /usr/local/sbin/codestra-production-operator "$action"' in text


def test_control_plane_rollback_restores_database_before_old_images_start() -> None:
    text = OPERATOR_PATH.read_text()
    rollback = text[text.index("def rollback_control_plane"):text.index("def safety_state")]
    assert '"dropdb"' in rollback
    assert '"createdb"' in rollback
    assert 'stdin=database_dump' in rollback
    assert rollback.index('stdin=database_dump') < rollback.index('"up", "--detach", "--no-build"')
    assert 'rollback_images = backup / "rollback-images.yaml"' in rollback
    assert f'codestra/{{CONTROL_PLANE_PROJECT}}-api:rollback-{{stamp}}' in rollback
    assert f'codestra/{{CONTROL_PLANE_PROJECT}}-worker:rollback-{{stamp}}' in rollback
    assert '"--file", str(rollback_images)' in rollback


def test_waiver_cannot_bypass_tuple_or_protected_approval() -> None:
    forced = (PACKAGE / "codestra-production-forced-command").read_text()
    workflow = (ROOT / ".github/workflows/production-activation.yml").read_text()
    assert 'parts[1:] != expected' in forced
    assert 'test "$(git -C release rev-parse HEAD)" = "${PROTECTED_SHA}"' in workflow
    assert 'ref: ${{ github.workflow_sha }}' in workflow
    assert "python authority/tools/validate_activation_request.py" in workflow
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
    assert 'STANDBY_ENTRYPOINT = ["/opt/venv/bin/python"]' in text
    assert 'STANDBY_COMMAND = ["-c", "import threading; threading.Event().wait()"]' in text
    assert '"--entrypoint", STANDBY_ENTRYPOINT[0]' in text
    assert 'subject, *STANDBY_COMMAND' in text
    assert "standby_configuration_matches(existing, subject)" in text
    assert '["/usr/bin/docker", "rm", STANDBY_CONTAINER]' in text
    assert 'host.get("ReadonlyRootfs") is True' in text
    assert 'host.get("CapDrop") == ["ALL"]' in text
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
    real_lstat = OPERATOR.Path.lstat
    real_fstat = OPERATOR.os.fstat

    def root_owned(info):
        return type(
            "RootOwnedStat",
            (),
            {"st_mode": info.st_mode, "st_uid": 0, "st_gid": 0},
        )()

    monkeypatch.setattr(OPERATOR.Path, "lstat", lambda path: root_owned(real_lstat(path)))
    monkeypatch.setattr(OPERATOR.os, "fstat", lambda descriptor: root_owned(real_fstat(descriptor)))
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
