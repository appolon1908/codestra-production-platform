from pathlib import Path


ROOT = Path(__file__).parents[1]
BACKUP = (ROOT / "operations/database-certification/backup-all-databases.sh").read_text()
RESTORE = (ROOT / "operations/database-certification/restore-all-databases.sh").read_text()
METRICS = (ROOT / "operations/monitoring/exporters/database_certification_metrics.sh").read_text()
RULES = (ROOT / "operations/monitoring/rules/database-certification.rules.yml").read_text()
RUNTIME = (ROOT / "operations/monitoring/exporters/database_runtime_metrics.sh").read_text()
RESTORE_SERVICE = (ROOT / "operations/systemd/codestra-database-certification-restore.service").read_text()


def test_backup_covers_every_discovered_database_authority():
    required = {
        "codestra-postgres-1",
        "codestra-kong-kong-db-1",
        "codestra-identity-identity-db-1",
        "codestra-websocket-gateway-postgres-1",
        "codestra-websocket-standby-031447a-postgres-1",
        "codestra-reseller-portal-postgres-1",
        "codestra-sms-api-postgres-1",
        "codestra-provisioning-service-provisioning-service-1",
    }
    assert all(name in BACKUP for name in required)
    assert "source.backup(target)" in BACKUP
    assert "sha256sum -c" in BACKUP
    assert "--encrypt" in BACKUP


def test_restore_is_isolated_and_cleans_up():
    assert "-p " not in RESTORE
    assert "docker volume rm" in RESTORE
    assert "--no-owner" in RESTORE
    assert "--exit-on-error" in RESTORE
    assert "PRAGMA integrity_check" in RESTORE
    assert "RESTORE_PUBLIC_PORTS=0" in RESTORE
    assert "ProtectSystem=strict" in RESTORE_SERVICE
    assert "ReadWritePaths=" in RESTORE_SERVICE
    assert "/etc/codestra/backup-gpg" in RESTORE_SERVICE


def test_offhost_is_fail_closed_not_falsely_certified():
    assert "offhost=PENDING" in BACKUP
    assert "OFFHOST_COPY=${offhost}" in BACKUP
    assert "sha256sum -c SHA256SUMS" in BACKUP
    assert "REMOTE-SHA256SUMS" in BACKUP
    assert "diff -u" in BACKUP


def test_database_certification_is_scheduled_and_monitored():
    assert "codestra_database_backup_offhost_ok" in METRICS
    assert "CodestraDatabaseBackupStale" in RULES
    assert "CodestraDatabaseRestoreOverdue" in RULES
    assert "CodestraWebsocketReplicationDown" in RULES
    assert "CodestraWebsocketStandbyUnexpectedlyWritable" in RULES
    assert "CodestraCanonicalDatabaseDown" in RULES
    assert "codestra_database_connections" in RUNTIME
    assert "codestra_websocket_db_standby_in_recovery" in RUNTIME
