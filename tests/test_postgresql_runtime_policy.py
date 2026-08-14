from pathlib import Path


def test_runtime_database_policy_is_non_owning_and_bounded() -> None:
    sql = Path("config/postgresql-runtime-policy.sql.example").read_text().upper()
    assert "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS" in sql
    assert "GRANT SELECT, INSERT, UPDATE" in sql
    assert "REVOKE DELETE, TRUNCATE" in sql
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE CODESTRA_MIDDLEWARE_MIGRATION_OWNER" in sql
    assert "ON TABLES TO CODESTRA_MIDDLEWARE_RUNTIME" in sql
    assert "ON SEQUENCES TO CODESTRA_MIDDLEWARE_RUNTIME" in sql
    assert sql.count("EXCEPTION WHEN DUPLICATE_OBJECT THEN NULL") == 2
    assert "ALTER ROLE CODESTRA_MIDDLEWARE_RUNTIME NOLOGIN NOSUPERUSER" in sql
    assert "GRANT ALL" not in sql
    assert "ALTER TABLE" not in sql
    assert " OWNER TO CODESTRA_MIDDLEWARE_RUNTIME" not in sql
    assert "DROP " not in sql
