from pathlib import Path


def test_runtime_database_policy_is_non_owning_and_bounded() -> None:
    sql = Path("config/postgresql-runtime-policy.sql.example").read_text().upper()
    assert "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS" in sql
    assert "GRANT SELECT, INSERT, UPDATE" in sql
    assert "REVOKE DELETE, TRUNCATE" in sql
    assert "GRANT ALL" not in sql
    assert "ALTER ROLE" not in sql
    assert "DROP " not in sql
