\set ON_ERROR_STOP on

BEGIN;

DO $migration$
BEGIN
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
ALTER SCHEMA reporting OWNER TO middleware_data_owner;
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
ALTER ROLE middleware_app NOLOGIN NOCREATEDB NOCREATEROLE NOSUPERUSER NOBYPASSRLS;

COMMIT;
