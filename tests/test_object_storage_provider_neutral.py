from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KONG = ROOT / "operations" / "kong-database"


def test_kong_backup_consumers_use_provider_neutral_object_credentials():
    for name in ("kong-database-backup.sh", "codestra-kong-wal-archive.sh"):
        value = (KONG / name).read_text()
        assert "/etc/codestra/backup/b2-" not in value
        assert "/etc/codestra/backup/object-access-key-id" in value
        assert "/etc/codestra/backup/object-secret-access-key" in value
        assert "/etc/codestra/backup/object-region" in value
        assert "/etc/codestra/backup/restic-repository" in value
