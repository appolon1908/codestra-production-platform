from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "operations" / "database" / "retire_middleware_app.sql"


def test_legacy_role_retirement_is_fail_closed_and_non_destructive():
    sql = MIGRATION.read_text()
    required = {
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        "REASSIGN OWNED BY middleware_app TO middleware_data_owner;",
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public, reporting FROM middleware_app;",
        "ALTER ROLE middleware_app NOLOGIN",
        "COMMIT;",
    }
    assert all(fragment in sql for fragment in required)
    assert "middleware_app still has active sessions" in sql
    assert "middleware_data_owner must exist as a NOLOGIN owner role" in sql
    assert "DROP " not in sql.upper()
    assert "DELETE " not in sql.upper()
    assert "TRUNCATE " not in sql.upper()
