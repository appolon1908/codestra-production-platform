import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "operations" / "shared-postgresql"


def test_source_has_required_restart_settings():
    value = (PACKAGE / "postgresql-pitr.conf").read_text()
    for setting in ("archive_mode = 'on'", "wal_level = 'replica'", "archive_command", "archive_timeout", "max_wal_senders", "max_replication_slots"):
        assert setting in value


def test_wal_and_base_backup_are_encrypted_checksummed_and_offhost():
    wal = (PACKAGE / "codestra-shared-postgres-archive-wal.sh").read_text()
    base = (PACKAGE / "create-base-backup.sh").read_text()
    for value in (wal, base):
        assert "gpg" in value and "--encrypt" in value
        assert "sha256sum" in value
        assert "restic backup" in value
        assert "PASSWORD=" not in value
    assert "pg_basebackup" in base and "-X fetch" in base
    assert '--keep-within "${retention_days}d"' in wal
    assert "--keep-weekly 8" in base and "--keep-monthly 12" in base


def test_alerts_cover_required_recovery_failures():
    rules = (PACKAGE / "shared-postgres.rules.yml").read_text()
    for alert in ("SharedPostgresWALArchiveFailure", "SharedPostgresWALArchiveStale", "SharedPostgresBaseBackupStale", "SharedPostgresPITRRehearsalOverdue", "SharedPostgresDiskWarning", "SharedPostgresDiskCritical"):
        assert f"alert: {alert}" in rules
    metrics = (PACKAGE / "shared-postgres-metrics.sh").read_text()
    for metric in (
        "wal_archive_failures_total",
        "wal_last_success_timestamp_seconds",
        "base_backup_last_success_timestamp_seconds",
        "pitr_last_success_timestamp_seconds",
        "disk_used_percent",
    ):
        assert f"codestra_shared_postgres_{metric}" in metrics


def test_restore_command_is_checksum_verified_and_isolated():
    restore = (PACKAGE / "codestra-shared-postgres-restore-wal.sh").read_text()
    settings = (PACKAGE / "recovery-settings.conf.example").read_text()
    assert "sha256sum -c" in restore and "gpg" in restore and "--decrypt" in restore
    assert "/recovery-archive/" in restore
    assert "restore_command" in settings and "recovery_target_time" in settings


def test_validator_fails_closed_on_template():
    result = subprocess.run(
        ["bash", str(PACKAGE / "validate-change-authority.sh"), str(PACKAGE / "approved-change.env.example")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "SHARED_POSTGRES_CUTOVER_GO=NO" in result.stdout


def test_validator_accepts_a_complete_synthetic_authority(tmp_path):
    evidence = []
    markers = ("BACKUP", "OFFHOST_BACKUP", "RESTORE_PRECHECK", "ROLLBACK_PRECHECK")
    for name, marker in zip(("backup", "offhost", "restore", "rollback"), markers):
        path = tmp_path / f"{name}.txt"
        path.write_text(f"{marker}=PASS\n")
        evidence.append(path)
    authority = tmp_path / "approved.env"
    authority.write_text(
        "\n".join(
            (
                "SHARED_CHANGE_ID=CHG-SYNTHETIC",
                "SHARED_CHANGE_STATUS=APPROVED",
                "SHARED_ACCOUNTABLE_OWNER=synthetic-owner",
                "SHARED_RECOVERY_OWNER=synthetic-recovery-owner",
                "SHARED_ROLLBACK_OWNER=synthetic-rollback-owner",
                "SHARED_RESTART_START=2099-01-01T00:00:00Z",
                "SHARED_RESTART_END=2099-01-01T02:00:00Z",
                "SHARED_TIMEZONE=UTC",
                "SHARED_RPO_SECONDS=300",
                "SHARED_RTO_SECONDS=900",
                "SHARED_WAL_RETENTION_DAYS=7",
                "SHARED_BASE_BACKUP_FREQUENCY=weekly",
                "SHARED_ARCHIVE_DESTINATION=synthetic-independent-authority",
                "SHARED_ARCHIVE_INDEPENDENT_AUTHORITY=YES",
                "SHARED_HA_DECISION=FORMALLY_NOT_REQUIRED",
                f"SHARED_BACKUP_EVIDENCE={evidence[0]}",
                f"SHARED_OFFHOST_EVIDENCE={evidence[1]}",
                f"SHARED_RESTORE_EVIDENCE={evidence[2]}",
                f"SHARED_ROLLBACK_EVIDENCE={evidence[3]}",
            )
        )
        + "\n"
    )
    result = subprocess.run(
        ["bash", str(PACKAGE / "validate-change-authority.sh"), str(authority)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "SHARED_POSTGRES_CUTOVER_GO=YES" in result.stdout


def test_validator_rejects_failed_recovery_evidence(tmp_path):
    template = (PACKAGE / "approved-change.env.example").read_text()
    authority = tmp_path / "failed.env"
    authority.write_text(template.replace("REQUIRED", "FAIL"))
    result = subprocess.run(
        ["bash", str(PACKAGE / "validate-change-authority.sh"), str(authority)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "SHARED_POSTGRES_CUTOVER_GO=NO" in result.stdout


def test_runbook_prohibits_early_middleware_migration():
    value = (PACKAGE / "PITR_RUNBOOK.md").read_text()
    assert "Only after PITR PASS" in value
    assert "Do not migrate middleware" in value
    assert "Never restore over production" in value


def test_postgres_stages_wal_without_backup_credentials():
    stage = (PACKAGE / "codestra-shared-postgres-stage-wal.sh").read_text()
    config = (PACKAGE / "postgresql-pitr.conf").read_text()
    assert "test \"$(id -u)\" -eq 0" not in stage
    assert "restic" not in stage and "gpg" not in stage
    assert "codestra-shared-postgres-stage-wal.sh" in config


def test_offload_worker_bounds_local_spool_after_verified_publication():
    worker = (PACKAGE / "codestra-shared-postgres-archive-wal.sh").read_text()
    assert "wal-retention-days" in worker
    assert "restic snapshots" in worker
    assert "touch \"$source_path.offhost\"" in worker
    assert "-mtime \"+$retention_days\"" in worker


def test_checksum_manifests_use_portable_basenames():
    wal = (PACKAGE / "codestra-shared-postgres-archive-wal.sh").read_text()
    base = (PACKAGE / "create-base-backup.sh").read_text()
    assert 'sha256sum "$wal_name.gpg"' in wal
    assert "sha256sum base.tar.gpg" in base
    assert 'sha256sum "$artifact"' not in wal
