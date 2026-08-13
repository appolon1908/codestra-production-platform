\set ON_ERROR_STOP on

-- Phase 1 is intentionally committed separately.  Once NOLOGIN is visible to
-- the cluster, no new legacy sessions can race the ownership migration.
BEGIN;

DO $preflight$
BEGIN
    IF current_database() <> 'codestra_middleware' THEN
        RAISE EXCEPTION
            'must run against codestra_middleware (connected to %)',
            current_database();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'middleware_app'
    ) THEN
        RAISE EXCEPTION 'middleware_app role does not exist';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'middleware_data_owner' AND NOT rolcanlogin
    ) THEN
        RAISE EXCEPTION
            'middleware_data_owner must exist as a NOLOGIN owner role';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_auth_members
        WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app')
    ) THEN
        RAISE EXCEPTION
            'middleware_app must not have member roles capable of SET ROLE';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_database
        WHERE datdba = (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app')
          AND datname <> 'codestra_middleware'
    ) THEN
        RAISE EXCEPTION
            'middleware_app owns an unexpected database';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_tablespace
        WHERE spcowner = (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app')
    ) THEN
        RAISE EXCEPTION
            'middleware_app owns an unexpected tablespace';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_default_acl
        WHERE defaclrole = (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app')
    ) THEN
        RAISE EXCEPTION
            'middleware_app has default ACLs requiring separate reviewed cleanup';
    END IF;
END
$preflight$;

ALTER ROLE middleware_app NOLOGIN NOCREATEDB NOCREATEROLE NOSUPERUSER NOBYPASSRLS;

COMMIT;

BEGIN;

DO $migration$
BEGIN
    IF current_database() <> 'codestra_middleware' THEN
        RAISE EXCEPTION
            'must run against codestra_middleware (connected to %)',
            current_database();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'middleware_data_owner' AND NOT rolcanlogin
    ) THEN
        RAISE EXCEPTION
            'middleware_data_owner must exist as a NOLOGIN owner role';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_stat_activity
        WHERE usename = 'middleware_app' AND pid <> pg_backend_pid()
    ) THEN
        RAISE EXCEPTION 'middleware_app still has active sessions';
    END IF;
END
$migration$;

DO $database_owner$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_database
        WHERE datname = 'codestra_middleware'
          AND datdba = (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app')
    ) THEN
        ALTER DATABASE codestra_middleware OWNER TO middleware_data_owner;
    END IF;
END
$database_owner$;

REASSIGN OWNED BY middleware_app TO middleware_data_owner;
REVOKE ALL PRIVILEGES ON DATABASE codestra_middleware FROM middleware_app;
REVOKE ALL PRIVILEGES ON SCHEMA public, reporting FROM middleware_app;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public, reporting FROM middleware_app;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public, reporting FROM middleware_app;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public, reporting FROM middleware_app;
DO $postcondition$
DECLARE
    legacy_oid oid := (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app');
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_depend
        WHERE refclassid = 'pg_authid'::regclass
          AND refobjid = legacy_oid
          AND deptype = 'o'
    ) OR EXISTS (
        SELECT 1
        FROM pg_shdepend
        WHERE refclassid = 'pg_authid'::regclass
          AND refobjid = legacy_oid
          AND deptype = 'o'
    ) THEN
        RAISE EXCEPTION
            'middleware_app still owns objects after REASSIGN OWNED';
    END IF;
END
$postcondition$;

COMMIT;
