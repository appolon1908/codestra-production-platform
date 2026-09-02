from pathlib import Path


def test_provider_attempt_migration_is_idempotent_and_durable():
    sql = (
        Path(__file__).parents[1]
        / "migrations/control_plane/006_provider_attempt.sql"
    ).read_text()
    assert "ADD COLUMN IF NOT EXISTS provider_attempt" in sql
    assert "integer NOT NULL DEFAULT 0" in sql
