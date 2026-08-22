#!/usr/bin/env python3
"""Inventory dedicated PostgreSQL application roles without exposing credentials.

This operator tool executes read-only catalog queries inside the owning database
containers. Credential values never leave the containers and are not included
in the generated CSV.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Target:
    application: str
    container: str


TARGETS = (
    Target("Keycloak", "codestra-identity-identity-db-1"),
    Target("Kong", "codestra-kong-kong-db-1"),
    Target("Reseller Portal", "codestra-reseller-portal-postgres-1"),
    Target("SMS API", "codestra-sms-api-postgres-1"),
    Target("Realtime WebSocket Gateway", "codestra-websocket-gateway-postgres-1"),
)


QUERY = r"""
WITH role_info AS (
  SELECT r.oid, r.rolname, r.rolcanlogin, r.rolsuper, r.rolcreatedb,
         r.rolcreaterole, r.rolbypassrls, r.rolinherit
  FROM pg_roles r
  WHERE r.rolname = current_user
), memberships AS (
  SELECT COALESCE(string_agg(parent.rolname, ';' ORDER BY parent.rolname), '') AS value
  FROM role_info ri
  LEFT JOIN pg_auth_members m ON m.member = ri.oid
  LEFT JOIN pg_roles parent ON parent.oid = m.roleid
), databases AS (
  SELECT COALESCE(string_agg(datname, ';' ORDER BY datname), '') AS value
  FROM pg_database d JOIN role_info ri ON d.datdba = ri.oid
), schemas AS (
  SELECT COALESCE(string_agg(nspname, ';' ORDER BY nspname), '') AS value
  FROM pg_namespace n JOIN role_info ri ON n.nspowner = ri.oid
  WHERE nspname NOT LIKE 'pg_toast%' AND nspname NOT LIKE 'pg_temp%'
), tables AS (
  SELECT count(*)::text AS value
  FROM pg_class c JOIN role_info ri ON c.relowner = ri.oid
  WHERE c.relkind IN ('r','p','v','m','S','f')
), defaults AS (
  SELECT COALESCE(string_agg(
    COALESCE(n.nspname, '*') || ':' || d.defaclobjtype::text || ':' ||
    COALESCE(array_to_string(d.defaclacl, ','), ''), ';' ORDER BY 1), '') AS value
  FROM pg_default_acl d
  JOIN role_info ri ON d.defaclrole = ri.oid
  LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
), connections AS (
  SELECT count(*)::text AS value FROM pg_stat_activity WHERE usename = current_user
)
SELECT ri.rolname, ri.rolcanlogin, ri.rolsuper, ri.rolcreatedb,
       ri.rolcreaterole, ri.rolbypassrls, ri.rolinherit,
       memberships.value, databases.value, schemas.value, tables.value,
       defaults.value, connections.value
FROM role_info ri, memberships, databases, schemas, tables, defaults, connections;
"""


def query(target: Target) -> list[str]:
    command = (
        "export PGOPTIONS='-c default_transaction_read_only=on'; "
        "psql -X -v ON_ERROR_STOP=1 -U \"$POSTGRES_USER\" "
        "-d \"$POSTGRES_DB\" -At -F '|' -c \""
        + QUERY.replace('"', '\\"').replace("\n", " ")
        + '"'
    )
    result = subprocess.run(
        ["docker", "exec", target.container, "sh", "-lc", command],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    values = result.stdout.strip().split("|")
    if len(values) != 13:
        raise RuntimeError(f"unexpected catalog result for {target.application}")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fields = (
        "ROLE", "APPLICATION", "LOGIN", "SUPERUSER", "CREATEDB", "CREATEROLE",
        "BYPASSRLS", "INHERIT", "MEMBER_OF", "OWNS_DATABASES", "OWNS_SCHEMAS",
        "OWNS_TABLES", "DEFAULT_PRIVILEGES", "ACTIVE_CONNECTION_COUNT",
    )
    rows = []
    for target in TARGETS:
        values = query(target)
        rows.append(dict(zip(fields, (values[0], target.application, *values[1:]))))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
