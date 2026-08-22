\set ON_ERROR_STOP on

-- Required psql variables:
--   app_role, owner_role, migration_role, runtime_create (true/false)
-- Run while connected to the application database as a protected cluster admin.

-- PostgreSQL 17 will never demote the immutable bootstrap superuser (OID 10).
-- Fail before changing ownership so such clusters are replaced through the
-- reviewed blue/green procedure instead of being left partially reconciled.
SELECT count(*) AS bootstrap_app_role
FROM pg_roles
WHERE rolname = :'app_role' AND oid = 10 \gset
\if :bootstrap_app_role
  \echo 'application role is immutable bootstrap superuser; blue/green cluster replacement required'
  \quit 5
\endif

SELECT format(
  'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'owner_role'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'owner_role') \gexec

SELECT format(
  'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT',
  :'migration_role'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_role') \gexec

-- The application login is never a member of either privileged role.
SELECT format('REVOKE %I FROM %I', :'owner_role', :'app_role') \gexec
SELECT format('REVOKE %I FROM %I', :'migration_role', :'app_role') \gexec
SELECT format('GRANT %I TO %I', :'owner_role', :'migration_role') \gexec

-- Transfer only application namespaces. PostgreSQL catalogs deliberately remain
-- under the bootstrap role; allow_system_table_mods remains off and the login
-- loses superuser authority below.
SELECT format('ALTER SCHEMA %I OWNER TO %I', n.nspname, :'owner_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
  AND n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = :'app_role')
ORDER BY n.nspname \gexec

SELECT format(
  'ALTER %s %I.%I OWNER TO %I',
  CASE c.relkind
    WHEN 'S' THEN 'SEQUENCE'
    WHEN 'v' THEN 'VIEW'
    WHEN 'm' THEN 'MATERIALIZED VIEW'
    WHEN 'f' THEN 'FOREIGN TABLE'
    ELSE 'TABLE'
  END,
  n.nspname, c.relname, :'owner_role'
)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
  AND c.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
  AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = :'app_role')
ORDER BY n.nspname, c.relname \gexec

SELECT format(
  'ALTER ROUTINE %I.%I(%s) OWNER TO %I',
  n.nspname, p.proname, pg_get_function_identity_arguments(p.oid), :'owner_role'
)
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
  AND p.proowner = (SELECT oid FROM pg_roles WHERE rolname = :'app_role')
ORDER BY n.nspname, p.proname, p.oid \gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', current_database(), :'owner_role') \gexec

-- A permanent synthetic fixture proves real table grants without touching
-- application or customer rows. It remains bounded to one TEST_SYN record.
CREATE TABLE IF NOT EXISTS public.codestra_rbac_probe (
  probe_id text PRIMARY KEY,
  probe_value integer NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.codestra_rbac_probe(probe_id, probe_value)
VALUES ('TEST_SYN', 1)
ON CONFLICT (probe_id) DO NOTHING;
SELECT format('ALTER TABLE public.codestra_rbac_probe OWNER TO %I', :'owner_role') \gexec

SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', current_database(), :'app_role') \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', current_database(), :'migration_role') \gexec

SELECT format('GRANT USAGE ON SCHEMA %I TO %I', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec

SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec

SELECT format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA %I TO %I', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec

SELECT format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA %I TO %I', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec

SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'owner_role', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec

SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'owner_role', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec

SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT EXECUTE ON FUNCTIONS TO %I', :'owner_role', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec

\if :runtime_create
SELECT format('GRANT CREATE ON DATABASE %I TO %I', current_database(), :'app_role') \gexec
SELECT format('GRANT CREATE ON SCHEMA %I TO %I', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec
\else
SELECT format('REVOKE CREATE ON DATABASE %I FROM %I', current_database(), :'app_role') \gexec
SELECT format('REVOKE CREATE ON SCHEMA %I FROM %I', n.nspname, :'app_role')
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
ORDER BY n.nspname \gexec
\endif

SELECT format(
  'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS INHERIT',
  :'app_role'
) \gexec

-- Fail closed if any required attribute or membership invariant is wrong.
SELECT count(*) AS app_attribute_violations
FROM pg_roles
WHERE rolname = :'app_role'
  AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls) \gset
\if :app_attribute_violations
  \echo 'application role attribute invariant failed'
  \quit 3
\endif

SELECT (
  pg_has_role(:'app_role', :'owner_role', 'MEMBER')::int
  + pg_has_role(:'app_role', :'migration_role', 'MEMBER')::int
) AS app_membership_violations \gset
\if :app_membership_violations
  \echo 'application role has forbidden privileged membership'
  \quit 4
\endif
