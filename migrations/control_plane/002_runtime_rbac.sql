BEGIN;
DO $$ BEGIN CREATE ROLE codestra_control_plane_owner NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE codestra_control_plane_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
ALTER ROLE codestra_control_plane_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE codestra_control_plane_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER SCHEMA control_plane OWNER TO codestra_control_plane_owner;
DO $$ DECLARE item record; BEGIN
  FOR item IN SELECT tablename FROM pg_tables WHERE schemaname='control_plane' LOOP
    EXECUTE format('ALTER TABLE control_plane.%I OWNER TO codestra_control_plane_owner',item.tablename);
  END LOOP;
END $$;
GRANT USAGE ON SCHEMA control_plane TO codestra_control_plane_runtime;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA control_plane TO codestra_control_plane_runtime;
REVOKE DELETE,TRUNCATE,REFERENCES,TRIGGER ON ALL TABLES IN SCHEMA control_plane FROM codestra_control_plane_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE codestra_control_plane_owner IN SCHEMA control_plane
 GRANT SELECT,INSERT,UPDATE ON TABLES TO codestra_control_plane_runtime;
COMMIT;
