from pathlib import Path


ROOT = Path(__file__).parents[1]
BACKUP = (ROOT / "operations/database-certification/backup-all-databases.sh").read_text()
RESTORE = (ROOT / "operations/database-certification/restore-all-databases.sh").read_text()
WAL = (ROOT / "operations/shared-postgresql/codestra-shared-postgres-archive-wal.sh").read_text()


def test_active_streaming_standby_is_selected_and_role_checked() -> None:
    assert "codestra-websocket-replica-postgres-1" in BACKUP
    assert "pg_is_in_recovery()" in BACKUP
    assert "pg_stat_wal_receiver where status='streaming'" in BACKUP
    assert "pg_wal_lsn_diff" in BACKUP


def test_standby_unavailable_primary_or_excess_lag_fail_closed() -> None:
    assert "docker inspect -f '{{.State.Status}}'" in BACKUP
    assert '[[ "$recovery" == t && "$receiving" == t && "$replaying" == t ]]' in BACKUP
    assert "lag <= standby_max_lag_bytes" in BACKUP


def test_current_provisioning_volume_is_authoritative() -> None:
    assert "codestra-provisioning-production_state" in BACKUP
    assert 'test "$current_mount" = "$provisioning_volume"' in BACKUP
    assert 'test "$provisioning_volume" != "$retired_provisioning_volume"' in BACKUP
    assert "codestra-provisioning-service_state:/var/lib/codestra" not in BACKUP


def test_backup_encryption_checksum_offhost_and_partial_failure_contracts() -> None:
    assert "--recipient \"$gpg_recipient\" --encrypt" in BACKUP
    assert "sha256sum -c SHA256SUMS" in BACKUP
    assert "REMOTE-SHA256SUMS" in BACKUP
    assert "DATABASE_BACKUP=FAIL" in BACKUP
    assert "OFFHOST_COPY=${offhost}" in BACKUP


def test_execution_is_locked_bounded_by_capacity_and_interrupt_safe() -> None:
    assert 'flock -n 9' in BACKUP
    assert "minimum_free_percent" in BACKUP
    assert "trap cleanup EXIT" in BACKUP
    assert 'find "$work" -xdev -type f -delete' in BACKUP


def test_restore_requires_all_databases_and_provisioning_sqlite() -> None:
    assert 'test "$count" -eq 10' in RESTORE
    assert "provisioning.sqlite3" in RESTORE
    assert "integrity_check" in RESTORE
    assert "DATABASE_RESTORE=PASS" in RESTORE


def test_retention_and_wal_contract_remain_seven_day_authority_driven() -> None:
    assert "wal-retention-days" in WAL
    assert '"$prune_helper" "$retention_days"' in WAL
    assert 'restic forget --quiet --tag shared-postgresql-wal --keep-within "${retention_days}d"' in WAL


def test_evidence_is_published_only_after_successful_artifact_checks() -> None:
    status_write = BACKUP.index('cat > "$final/STATUS.txt"')
    checksum = BACKUP.index('sha256sum -c SHA256SUMS')
    assert checksum < status_write
    assert 'sha256sum "$final/STATUS.txt" > "$final/EVIDENCE-SHA256SUMS"' in BACKUP
