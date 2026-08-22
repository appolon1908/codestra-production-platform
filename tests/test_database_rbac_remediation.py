from pathlib import Path


SQL = Path("operations/database-rbac/reconcile_application_role.sql").read_text()


def test_application_role_loses_cluster_privileges():
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS" in SQL


def test_application_role_cannot_inherit_owner_or_migrator():
    assert "REVOKE %I FROM %I', :'owner_role', :'app_role'" in SQL
    assert "REVOKE %I FROM %I', :'migration_role', :'app_role'" in SQL
    assert "forbidden privileged membership" in SQL


def test_only_migrator_receives_owner_membership():
    assert "GRANT %I TO %I', :'owner_role', :'migration_role'" in SQL


def test_runtime_grants_are_application_scoped():
    assert "pg_catalog', 'information_schema'" in SQL
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" in SQL
    assert "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES" in SQL
    assert "GRANT EXECUTE ON ALL FUNCTIONS" in SQL


def test_create_is_explicitly_gated():
    assert "\\if :runtime_create" in SQL
    assert "GRANT CREATE ON DATABASE" in SQL
    assert "REVOKE CREATE ON DATABASE" in SQL
    assert "REVOKE CREATE ON SCHEMA" in SQL


def test_verifier_never_accepts_password_argument():
    source = Path("scripts/verify_postgres_app_role.py").read_text()
    assert "--password" not in source
    assert "stderr" not in source[source.index("print(json.dumps"):]
