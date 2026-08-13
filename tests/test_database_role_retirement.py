from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "operations" / "database" / "retire_middleware_app.sql"


def test_legacy_role_retirement_is_fail_closed_and_non_destructive():
    sql = MIGRATION.read_text()
    required = {
        "\\set ON_ERROR_STOP on",
        "current_database() <> 'codestra_middleware'",
        "ALTER ROLE middleware_app NOLOGIN",
        "REASSIGN OWNED BY middleware_app TO middleware_data_owner;",
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public, reporting FROM middleware_app;",
        "middleware_app still owns objects after REASSIGN OWNED",
        "middleware_app must not have member roles capable of SET ROLE",
        "middleware_app owns an unexpected database",
        "middleware_app owns an unexpected tablespace",
        "middleware_app has default ACLs requiring separate reviewed cleanup",
        "FROM pg_default_acl",
        "FROM pg_depend",
        "FROM pg_shdepend",
    }
    assert all(fragment in sql for fragment in required)
    assert "middleware_app still has active sessions" in sql
    assert "middleware_data_owner must exist as a NOLOGIN owner role" in sql
    assert "DROP " not in sql.upper()
    assert "DELETE " not in sql.upper()
    assert "TRUNCATE " not in sql.upper()


def test_login_is_disabled_and_committed_before_session_drain():
    sql = MIGRATION.read_text()
    no_login = sql.index("ALTER ROLE middleware_app NOLOGIN")
    first_commit = sql.index("COMMIT;", no_login)
    active_session_check = sql.index("middleware_app still has active sessions")
    assert no_login < first_commit < active_session_check


def test_reporting_owner_is_not_overwritten_unconditionally():
    sql = MIGRATION.read_text()
    assert "ALTER SCHEMA reporting OWNER" not in sql


def test_shared_ownership_is_bounded_before_reassign_owned():
    sql = MIGRATION.read_text()
    reassign = sql.index("REASSIGN OWNED BY middleware_app")
    assert sql.index("datname <> 'codestra_middleware'") < reassign
    assert sql.index("FROM pg_tablespace") < reassign
    assert sql.index("ALTER DATABASE codestra_middleware OWNER") < reassign


def test_postcondition_uses_ownership_dependency_catalogs():
    sql = MIGRATION.read_text()
    postcondition = sql.index("DO $postcondition$")
    assert sql.index("FROM pg_depend", postcondition) > postcondition
    assert sql.index("FROM pg_shdepend", postcondition) > postcondition
    assert sql.count("deptype = 'o'") == 2


def test_migration_does_not_create_legacy_default_acl_entries():
    sql = MIGRATION.read_text()
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE middleware_app" not in sql
    assert sql.index("FROM pg_default_acl") < sql.index(
        "ALTER ROLE middleware_app NOLOGIN"
    )
