import hashlib
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "operations" / "shared-postgresql"


def test_activation_compose_projects_stage_helper_without_secrets() -> None:
    activation = yaml.safe_load((PACKAGE / "compose.pitr-activation.yaml").read_text())
    postgres = activation["services"]["postgres"]
    command = postgres["command"]
    volumes = postgres["volumes"]
    assert "archive_mode=on" in command
    assert any(value.startswith("archive_command=") for value in command)
    assert (
        "/usr/local/sbin/codestra-shared-postgres-stage-wal.sh:"
        "/usr/local/sbin/codestra-shared-postgres-stage-wal.sh:ro"
    ) in volumes
    assert (
        "/var/spool/codestra/postgresql-shared/wal:"
        "/var/spool/codestra/postgresql-shared/wal"
    ) in volumes
    serialized = str(activation).lower()
    assert "password" not in serialized
    assert "private" not in serialized


def test_backup_hba_is_role_specific_scram_and_reload_only() -> None:
    script = (PACKAGE / "install-backup-hba.sh").read_text()
    assert "host replication $role $cidr scram-sha-256" in script
    assert "select pg_reload_conf()" in script
    assert "pg_hba_file_rules" in script
    assert "requested.is_private" in script
    assert "requested not in attached" in script
    assert "trap rollback EXIT" in script
    assert 'equivalent=$(psql' in script
    assert "host replication all" not in script
    assert "trust" not in script
    assert "docker restart" not in script


def run_validator(authority: Path):
    return subprocess.run(["bash", str(PACKAGE / "validate-change-authority.sh"), str(authority)], text=True, capture_output=True)


def evidence(tmp_path: Path, name: str, kind: str, change="CHG-SYNTHETIC", status="PASS", age=0):
    artifact = tmp_path / f"{name}.artifact"
    artifact.write_bytes(f"{name}-recovery-artifact".encode())
    artifact.chmod(0o600)
    captured = datetime.now(timezone.utc) - timedelta(seconds=age)
    path = tmp_path / f"{name}.evidence"
    path.write_text("\n".join((
        f"CHANGE_ID={change}", f"EVIDENCE_TYPE={kind}", f"STATUS={status}",
        f"CAPTURED_AT={captured.isoformat()}", "SOURCE_HOST=synthetic.internal",
        f"ARTIFACT_PATH={artifact}", f"ARTIFACT_SHA256={hashlib.sha256(artifact.read_bytes()).hexdigest()}",
        f"EXPIRES_AT={(captured + timedelta(days=2)).isoformat()}", "",
    )))
    path.chmod(0o600)
    return path


def authority(tmp_path: Path, overrides=None):
    now = datetime.now(timezone.utc)
    values = {
        "SHARED_CHANGE_ID": "CHG-SYNTHETIC", "SHARED_CHANGE_STATUS": "APPROVED",
        "SHARED_ACCOUNTABLE_OWNER": "owner", "SHARED_RECOVERY_OWNER": "recovery",
        "SHARED_ROLLBACK_OWNER": "rollback", "SHARED_RESTART_START": (now-timedelta(minutes=5)).isoformat(),
        "SHARED_RESTART_END": (now+timedelta(minutes=30)).isoformat(), "SHARED_TIMEZONE": "UTC",
        "SHARED_RPO_SECONDS": "300", "SHARED_RTO_SECONDS": "900", "SHARED_WAL_RETENTION_DAYS": "7",
        "SHARED_BASE_BACKUP_FREQUENCY": "weekly_and_before_every_cluster_change",
        "SHARED_ARCHIVE_DESTINATION": "independent", "SHARED_ARCHIVE_INDEPENDENT_AUTHORITY": "YES",
        "SHARED_HA_DECISION": "REQUIRED",
        "SHARED_BACKUP_EVIDENCE": str(evidence(tmp_path, "backup", "LOGICAL_BACKUP")),
        "SHARED_OFFHOST_EVIDENCE": str(evidence(tmp_path, "offhost", "OFFHOST_READBACK")),
        "SHARED_RESTORE_EVIDENCE": str(evidence(tmp_path, "restore", "RESTORE_PRECHECK")),
        "SHARED_ROLLBACK_EVIDENCE": str(evidence(tmp_path, "rollback", "ROLLBACK_PRECHECK")),
    }
    values.update(overrides or {})
    path = tmp_path / "approved.env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    path.chmod(0o600)
    return path, values


def test_source_has_valid_pitr_and_base_backup_contracts():
    config = (PACKAGE / "postgresql-pitr.conf").read_text()
    base = (PACKAGE / "create-base-backup.sh").read_text()
    for setting in ("archive_mode = 'on'", "wal_level = 'replica'", "archive_command", "archive_timeout", "max_wal_senders", "max_replication_slots"):
        assert setting in config
    assert "-Ft -X fetch" in base and "backup_manifest" in base and "pg_verifybackup" in base
    assert 'find "$work/verify/pg_wal"' in base
    assert 'chown "$postgres_uid:$postgres_gid" "$work/pgpass"' in base
    assert "shred -u" in base and "--encrypt" in base and "restic dump" in base
    assert 'restic backup --quiet --json' in base and 'get("snapshot_id", value)' in base
    restore = (PACKAGE / "codestra-shared-postgres-restore-wal.sh").read_text()
    assert 'mktemp -d' in restore and 'cp -a "$secrets/gpg/."' in restore and "shred -u" in restore


def test_offload_service_uses_protected_non_home_ssh_authority():
    unit = (PACKAGE / "codestra-shared-postgres-wal-offload.service").read_text()
    ssh_config = (PACKAGE / "codestra-shared-backup.ssh.conf").read_text()
    assert "ProtectHome=true" in unit
    assert "Environment=HOME=/etc/codestra/secrets/shared-postgresql/ssh-home" in unit
    assert "ReadOnlyPaths=/etc/codestra/secrets/shared-postgresql" in unit
    assert "Host codestra-shared-backup" in ssh_config
    assert "IdentityFile /etc/codestra/secrets/shared-postgresql/ssh-home/.ssh/id_ed25519" in ssh_config
    assert "StrictHostKeyChecking yes" in ssh_config and "BatchMode yes" in ssh_config
    resolved = subprocess.run(
        ["ssh", "-F", str(PACKAGE / "codestra-shared-backup.ssh.conf"), "-G", "codestra-shared-backup"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.lower()
    assert "hostname 10.40.0.2" in resolved
    assert "identitiesonly yes" in resolved
    assert "stricthostkeychecking true" in resolved
    assert "identityfile /etc/codestra/secrets/shared-postgresql/ssh-home/.ssh/id_ed25519" in resolved


def test_nonroot_stage_and_portable_checksum_relocation(tmp_path):
    if os.geteuid() == 0:
        tmp_path.chmod(0o755)
        tmp_path.parent.chmod(0o755)
        tmp_path.parent.parent.chmod(0o755)
    stage = tmp_path / "stage"; stage.mkdir(mode=0o700)
    source = tmp_path / "source"; source.write_bytes(os.urandom(1024)); source.chmod(0o644)
    stage_script = tmp_path / "stage.sh"
    shutil.copy2(PACKAGE / "codestra-shared-postgres-stage-wal.sh", stage_script)
    stage_script.chmod(0o755)
    command = ["bash", str(stage_script), str(source), "000000010000000000000001"]
    if os.geteuid() == 0:
        shutil.chown(stage, user="nobody", group="nogroup")
        command = ["setpriv", "--reuid=nobody", "--regid=nogroup", "--clear-groups", *command]
    wal = "000000010000000000000001"
    env = {**os.environ, "CODESTRA_SHARED_WAL_STAGE": str(stage)}
    result = subprocess.run(command, env=env)
    assert result.returncode == 0 and (stage / wal).read_bytes() == source.read_bytes()
    first = tmp_path / "first"; second = tmp_path / "second"; first.mkdir(); second.mkdir()
    artifact = first / "wal.gpg"; artifact.write_bytes(os.urandom(128))
    subprocess.run(["sha256sum", artifact.name], cwd=first, stdout=(first / "wal.gpg.sha256").open("w"), check=True)
    shutil.copy2(artifact, second); shutil.copy2(first / "wal.gpg.sha256", second)
    assert subprocess.run(["sha256sum", "-c", "wal.gpg.sha256"], cwd=second).returncode == 0


def test_nonroot_stage_accepts_timeline_history(tmp_path):
    if os.geteuid() == 0:
        tmp_path.chmod(0o755); tmp_path.parent.chmod(0o755); tmp_path.parent.parent.chmod(0o755)
    stage = tmp_path / "stage"; stage.mkdir(mode=0o700)
    source = tmp_path / "source"; source.write_text("timeline history"); source.chmod(0o644)
    script = tmp_path / "stage.sh"; shutil.copy2(PACKAGE / "codestra-shared-postgres-stage-wal.sh", script); script.chmod(0o755)
    command = ["bash", str(script), str(source), "00000002.history"]
    if os.geteuid() == 0:
        shutil.chown(stage, user="nobody", group="nogroup")
        command = ["setpriv", "--reuid=nobody", "--regid=nogroup", "--clear-groups", *command]
    result = subprocess.run(command, env={**os.environ, "CODESTRA_SHARED_WAL_STAGE": str(stage)})
    assert result.returncode == 0 and (stage / "00000002.history").read_text() == "timeline history"


@pytest.mark.parametrize("mutation,gate", [
    ({"empty": True}, "FILE_SECURITY"), ({"status": "FAIL"}, "STATUS"),
    ({"change": "WRONG"}, "CHANGE_ID"), ({"age": 7200}, "STALE"), ({"mismatch": True}, "CHECKSUM"),
])
def test_validator_rejects_bad_evidence(tmp_path, mutation, gate):
    auth, values = authority(tmp_path)
    target = Path(values["SHARED_BACKUP_EVIDENCE"])
    if mutation.get("empty"):
        target.write_text("")
    elif mutation.get("status"):
        target.write_text(target.read_text().replace("STATUS=PASS", f"STATUS={mutation['status']}"))
    elif mutation.get("change"):
        target.write_text(target.read_text().replace("CHANGE_ID=CHG-SYNTHETIC", f"CHANGE_ID={mutation['change']}"))
    elif mutation.get("age"):
        replacement = evidence(tmp_path, "stale", "LOGICAL_BACKUP", age=mutation["age"])
        auth.write_text(auth.read_text().replace(str(target), str(replacement)))
    elif mutation.get("mismatch"):
        lines = target.read_text().splitlines()
        target.write_text("\n".join("ARTIFACT_SHA256=" + "0" * 64 if line.startswith("ARTIFACT_SHA256=") else line for line in lines) + "\n")
    result = run_validator(auth)
    assert result.returncode != 0 and "SHARED_POSTGRES_CUTOVER_GO=NO" in result.stdout and gate in result.stdout


def test_validator_rejects_symlink_and_world_readable_evidence(tmp_path):
    auth, values = authority(tmp_path)
    target = Path(values["SHARED_BACKUP_EVIDENCE"]); target.chmod(0o644)
    assert "FILE_SECURITY" in run_validator(auth).stdout
    target.chmod(0o600); link = tmp_path / "link"; link.symlink_to(target)
    auth.write_text(auth.read_text().replace(str(target), str(link)))
    assert "FILE_SECURITY" in run_validator(auth).stdout


def test_validator_accepts_complete_fresh_packet(tmp_path):
    auth, _ = authority(tmp_path)
    result = run_validator(auth)
    assert result.returncode == 0 and "SHARED_POSTGRES_CUTOVER_GO=YES" in result.stdout


def test_validator_template_and_inactive_window_fail_closed(tmp_path):
    assert run_validator(PACKAGE / "approved-change.env.example").returncode != 0
    future = datetime.now(timezone.utc) + timedelta(days=1)
    auth, _ = authority(tmp_path, {"SHARED_RESTART_START": future.isoformat(), "SHARED_RESTART_END": (future+timedelta(hours=1)).isoformat()})
    assert "RESTART_WINDOW_INACTIVE" in run_validator(auth).stdout


def test_wal_worker_has_verified_bounded_retention_and_metrics():
    worker = (PACKAGE / "codestra-shared-postgres-archive-wal.sh").read_text()
    assert "--no-options --lock-never" in worker
    assert "--no-auto-check-trustdb" in worker
    rules = (PACKAGE / "shared-postgres.rules.yml").read_text()
    assert "restic dump" in worker and "OFFHOST_STATUS=PASS" not in worker
    assert "STATUS=PASS" in worker and "wal-retention-days" in worker and "-mtime" in worker
    assert "recorded_snapshot" in worker and "continue" in worker
    assert "wal_spool_disk_critical" in worker and "critical WAL spool filesystem usage" in worker
    assert "CODESTRA_SHARED_WAL_MAX_FILES_PER_RUN" in worker
    assert "processed < max_files" in worker
    assert 'df -P "$spool"' in worker
    assert 'find "$artifact" "$artifact.sha256" -delete' in worker
    assert "exit 1" not in worker
    assert "SharedPostgresWALSpoolCleanupFailure" in rules


def test_metrics_use_actual_offhost_success_and_support_timeline_history():
    metrics = (PACKAGE / "shared-postgres-metrics.sh").read_text()
    rules = (PACKAGE / "shared-postgres.rules.yml").read_text()
    restore = (PACKAGE / "codestra-shared-postgres-restore-wal.sh").read_text()
    assert "LAST_OFFHOST_SUCCESS" in metrics
    assert "codestra_shared_postgres_wal_offhost_last_success_timestamp_seconds" in metrics
    assert "codestra_shared_postgres_wal_offhost_last_success_timestamp_seconds" in rules
    assert ".history" in restore


def test_spool_cleanup_removes_only_verified_expired_wal(tmp_path):
    stage = tmp_path / "stage"; state = tmp_path / "state"; stage.mkdir(); state.mkdir()
    verified = stage / "000000010000000000000001"; verified.write_text("wal")
    verified_marker = Path(str(verified) + ".offhost")
    verified_marker.write_text("EVIDENCE_TYPE=WAL_OFFHOST\nSTATUS=PASS\n")
    failed = stage / "000000010000000000000002"; failed.write_text("wal")
    failed_marker = Path(str(failed) + ".offhost")
    failed_marker.write_text("EVIDENCE_TYPE=WAL_OFFHOST\nSTATUS=FAIL\n")
    old = (datetime.now().timestamp() - 9 * 86400)
    os.utime(verified_marker, (old, old)); os.utime(failed_marker, (old, old))
    env = {**os.environ, "CODESTRA_SHARED_WAL_STAGE": str(stage), "CODESTRA_SHARED_POSTGRES_STATE": str(state)}
    subprocess.run(["bash", str(PACKAGE / "codestra-shared-postgres-prune-wal.sh"), "7"], env=env, check=True)
    assert not verified.exists() and not verified_marker.exists()
    assert failed.exists() and failed_marker.exists()
    assert (state / "wal_cleanup_deleted_total").read_text().strip() == "1"
    assert (state / "wal_cleanup_failures_total").read_text().strip() == "1"


def test_runbook_prohibits_early_migration_and_overwrite():
    text = (PACKAGE / "PITR_RUNBOOK.md").read_text()
    assert "Only after PITR PASS" in text and "Do not migrate middleware" in text and "Never restore over production" in text
