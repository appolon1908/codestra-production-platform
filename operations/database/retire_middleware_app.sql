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

REASSIGN OWNED BY middleware_app TO middleware_data_owner;
REVOKE ALL PRIVILEGES ON DATABASE codestra_middleware FROM middleware_app;
REVOKE ALL PRIVILEGES ON SCHEMA public, reporting FROM middleware_app;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public, reporting FROM middleware_app;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public, reporting FROM middleware_app;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public, reporting FROM middleware_app;
ALTER DEFAULT PRIVILEGES FOR ROLE middleware_app
    REVOKE ALL ON TABLES FROM middleware_app;
ALTER DEFAULT PRIVILEGES FOR ROLE middleware_app
    REVOKE ALL ON SEQUENCES FROM middleware_app;
ALTER DEFAULT PRIVILEGES FOR ROLE middleware_app
    REVOKE ALL ON FUNCTIONS FROM middleware_app;

DO $postcondition$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relowner = (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app')
    ) OR EXISTS (
        SELECT 1
        FROM pg_namespace
        WHERE nspowner = (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app')
    ) OR EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE proowner = (SELECT oid FROM pg_roles WHERE rolname = 'middleware_app')
    ) THEN
        RAISE EXCEPTION
            'middleware_app still owns objects after REASSIGN OWNED';
    END IF;
END
$postcondition$;

COMMIT;
