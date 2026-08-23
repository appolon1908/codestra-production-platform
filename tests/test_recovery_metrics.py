from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recovery_exporter_requires_encrypted_backup_and_isolated_restore():
    source = (ROOT / "operations/monitoring/exporters/recovery_metrics.sh").read_text()
    for gate in (
        "BACKUP_STATUS=PASS",
        "ENCRYPTED=PASS",
        "DATABASE_RESTORE=PASS",
        "RESTORE_PUBLIC_PORTS=0",
        "RESTORE_RESIDUAL_RESOURCES=0",
    ):
        assert gate in source
    assert "codestra_backup_last_success_timestamp_seconds" in source
    assert "codestra_restore_test_last_success_timestamp_seconds" in source


def test_recovery_metrics_timer_is_recurring_and_hardened():
    service = (ROOT / "operations/systemd/codestra-recovery-metrics.service").read_text()
    timer = (ROOT / "operations/systemd/codestra-recovery-metrics.timer").read_text()
    assert "ProtectSystem=strict" in service
    assert "NoNewPrivileges=true" in service
    assert "OnUnitActiveSec=5m" in timer
    assert "Persistent=true" in timer
