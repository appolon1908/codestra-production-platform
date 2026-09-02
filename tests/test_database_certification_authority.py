from pathlib import Path


ROOT = Path(__file__).parents[1]
CERTIFICATION = ROOT / "operations/database-certification"
BACKUP = (CERTIFICATION / "backup-all-databases.sh").read_text()
RESTORE = (CERTIFICATION / "restore-all-databases.sh").read_text()
METRICS = (CERTIFICATION / "database-certification-metrics.sh").read_text()
BACKUP_SERVICE = (
    CERTIFICATION / "systemd/codestra-database-certification-backup.service"
).read_text()
RESTORE_SERVICE = (
    CERTIFICATION / "systemd/codestra-database-certification-restore.service"
).read_text()
RULES = ROOT / "operations/monitoring/rules/database-certification.rules.yml"
LEGACY_RULES = CERTIFICATION / "database-certification.rules.yml"
WAL = (
    ROOT / "operations/shared-postgresql/codestra-shared-postgres-archive-wal.sh"
).read_text()


def test_active_streaming_standby_is_selected_and_role_checked() -> None:
    assert "codestra-websocket-gateway-postgres-1" in BACKUP
    assert "codestra-websocket-replica-postgres-1" in BACKUP
    assert "pg_is_in_recovery()" in BACKUP
    assert "pg_stat_wal_receiver where status='streaming'" in BACKUP
    assert "pg_last_wal_replay_lsn()::text" in BACKUP


def test_standby_lag_is_measured_against_primary_flush_position() -> None:
    assert "pg_current_wal_flush_lsn()::text" in BACKUP
    assert (
        "pg_wal_lsn_diff('${primary_lsn}'::pg_lsn,"
        "'${replay_lsn}'::pg_lsn)"
    ) in BACKUP
    assert '[[ "$primary_recovery" == f ]]' in BACKUP
    assert '[[ "$recovery" == t && "$receiving" == t ]]' in BACKUP
    assert "lag <= standby_max_lag_bytes" in BACKUP
    assert "greatest(pg_wal_lsn_diff" not in BACKUP
    assert "lag >= 0" in BACKUP
    assert (
        "pg_wal_lsn_diff(pg_last_wal_receive_lsn(),"
        "pg_last_wal_replay_lsn())"
    ) not in BACKUP


def test_current_provisioning_volume_is_authoritative() -> None:
    assert "codestra-provisioning-production_state" in BACKUP
    assert 'test "$current_mount" = "$provisioning_volume"' in BACKUP
    assert 'test "$provisioning_volume" != "$retired_provisioning_volume"' in BACKUP
    assert "codestra-provisioning-service_state:/var/lib/codestra" not in BACKUP
    assert "codestra-provisioning-production_state/_data" in BACKUP_SERVICE


def test_backup_encryption_checksum_offhost_and_partial_failure_contracts() -> None:
    assert '--recipient "$gpg_recipient" --encrypt' in BACKUP
    assert "sha256sum -c SHA256SUMS" in BACKUP
    assert "REMOTE-SHA256SUMS" in BACKUP
    assert "DATABASE_BACKUP=FAIL" in BACKUP
    assert "OFFHOST_COPY=${offhost}" in BACKUP
    assert "backup_complete=false" in BACKUP
    assert '[[ "$backup_complete" != true && -d "$final" ]]' in BACKUP


def test_execution_is_locked_bounded_by_capacity_and_interrupt_safe() -> None:
    assert "flock -n 9" in BACKUP
    assert "minimum_free_percent" in BACKUP
    assert "trap cleanup EXIT" in BACKUP
    assert 'find "$work" -xdev -type f -delete' in BACKUP


def test_successful_backups_apply_bounded_verified_retention() -> None:
    assert "CODESTRA_DATABASE_BACKUP_RETENTION_DAYS" in BACKUP
    assert "retention_days >= 7 && retention_days <= 365" in BACKUP
    assert "prune_completed_backups" in BACKUP
    assert "sha256sum -c EVIDENCE-SHA256SUMS" in BACKUP
    assert 'find "$candidate" -xdev -depth -delete' in BACKUP
    assert "LOCAL_RETENTION_DAYS=${retention_days}" in BACKUP
    assert BACKUP.index("prune_completed_backups\navailable_percent=") < BACKUP.index(
        '(( available_percent >= minimum_free_percent ))'
    )


def test_restore_selects_newest_verified_completed_backup() -> None:
    assert "select_latest_completed_backup" in RESTORE
    assert "sort -r" in RESTORE
    assert "DATABASE_BACKUP=PASS" in RESTORE
    assert "CHECKSUM=PASS" in RESTORE
    assert "ENCRYPTION=PASS" in RESTORE
    assert "sha256sum -c EVIDENCE-SHA256SUMS" in RESTORE
    assert "REASON=no-verified-completed-backup" in RESTORE


def test_restore_requires_all_databases_and_provisioning_sqlite() -> None:
    assert 'test "$count" -eq 10' in RESTORE
    assert "provisioning.sqlite3" in RESTORE
    assert "integrity_check" in RESTORE
    assert "DATABASE_RESTORE=PASS" in RESTORE


def test_restore_verifies_cleanup_before_zero_residual_pass() -> None:
    cleanup = RESTORE.index("# Remove and positively verify disposable resources")
    evidence = RESTORE.index('cat > "$final/RESTORE-RESULT.txt"')
    assert cleanup < evidence
    assert 'assert_runtime_resource_absent container "$container"' in RESTORE[cleanup:evidence]
    assert 'assert_runtime_resource_absent volume "$volume"' in RESTORE[cleanup:evidence]
    assert "REASON=residual-container" in RESTORE
    assert "REASON=residual-volume" in RESTORE
    assert "RESTORE_RESIDUAL_RESOURCES=0" in RESTORE[evidence:]
    assert "assert_runtime_resource_absent" in RESTORE
    assert "No such object" in RESTORE
    assert "No such volume" in RESTORE


def test_metrics_publish_each_available_evidence_class_independently() -> None:
    assert "select_latest_valid_backup" in METRICS
    assert "select_latest_valid_restore" in METRICS
    assert "latest_backup=$(select_latest_valid_backup || true)" in METRICS
    assert "latest_restore=$(select_latest_valid_restore || true)" in METRICS
    assert 'if [[ -n "$latest_backup" ]]; then' in METRICS
    assert 'if [[ -n "$latest_restore" ]]; then' in METRICS
    assert 'test -n "$latest_backup" -a -n "$latest_restore"' not in METRICS
    assert "codestra_websocket_db_replication_lag_bytes" in METRICS
    assert "must not abort publication" in METRICS
    assert "backup_epoch=$(to_epoch" in METRICS


def test_systemd_units_invoke_packaged_metrics_and_allow_atomic_output() -> None:
    expected = (
        "ExecStartPost=/opt/codestra/operations/database-certification/"
        "database-certification-metrics.sh"
    )
    assert expected in BACKUP_SERVICE
    assert expected in RESTORE_SERVICE
    assert "/var/lib/node_exporter/textfile_collector" in BACKUP_SERVICE
    assert "/var/lib/node_exporter/textfile_collector" in RESTORE_SERVICE
    assert "/operations/monitoring/exporters/database_certification_metrics.sh" not in (
        BACKUP_SERVICE + RESTORE_SERVICE
    )


def test_rules_are_inside_prometheus_mounted_rule_directory() -> None:
    assert RULES.is_file()
    assert not LEGACY_RULES.exists()
    text = RULES.read_text()
    assert "CodestraDatabaseBackupStale" in text
    assert "CodestraDatabaseRestoreOverdue" in text
    assert "CodestraWebsocketReplicationLag" in text


def test_retention_and_wal_contract_remain_authority_driven() -> None:
    assert "CODESTRA_DATABASE_BACKUP_RETENTION_DAYS" in BACKUP
    assert "wal-retention-days" in WAL
    assert '"$prune_helper" "$retention_days"' in WAL
    assert (
        'restic forget --quiet --tag shared-postgresql-wal '
        '--keep-within "${retention_days}d"'
    ) in WAL


def test_evidence_is_published_only_after_successful_artifact_checks() -> None:
    status_write = BACKUP.index('cat > "$final/STATUS.txt"')
    checksum = BACKUP.index("sha256sum -c SHA256SUMS")
    assert checksum < status_write
    assert 'sha256sum "$final/STATUS.txt" > "$final/EVIDENCE-SHA256SUMS"' in BACKUP
