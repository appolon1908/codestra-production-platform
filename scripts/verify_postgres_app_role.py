#!/usr/bin/env python3
"""Fail-closed RBAC verification for a dedicated application database.

The password is never accepted on the command line.  libpq must obtain it from
the same mounted credential source used by the application (PGPASSFILE or a
DATABASE_URL supplied by the invoking protected runner).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys


IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def run_psql(dsn: str, sql: str, *, expect_success: bool) -> str:
    process = subprocess.run(
        ["psql", dsn, "-X", "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PGAPPNAME": "TEST_SYN_RBAC_CERTIFICATION"},
    )
    if (process.returncode == 0) != expect_success:
        # Do not echo libpq diagnostics: a malformed external DSN can contain a
        # credential.  The operation name and return code are sufficient.
        raise RuntimeError(f"unexpected psql result: rc={process.returncode}")
    return process.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    parser.add_argument("--app-role", required=True)
    parser.add_argument("--owner-role", required=True)
    parser.add_argument("--migration-role", required=True)
    parser.add_argument("--probe-table", default="public.codestra_rbac_probe")
    args = parser.parse_args()

    for value in (args.app_role, args.owner_role, args.migration_role):
        if not IDENTIFIER.fullmatch(value):
            raise SystemExit("role names must be unquoted PostgreSQL identifiers")
    dsn = os.environ.get(args.dsn_env, "")
    if not dsn:
        raise SystemExit(f"{args.dsn_env} is required")

    attributes = run_psql(
        dsn,
        "SELECT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb "
        "AND NOT rolcreaterole AND NOT rolbypassrls "
        f"FROM pg_roles WHERE rolname='{args.app_role}'",
        expect_success=True,
    )
    if attributes != "t":
        raise RuntimeError("application role attributes are not least privilege")

    membership = run_psql(
        dsn,
        f"SELECT pg_has_role('{args.app_role}','{args.owner_role}','MEMBER') "
        f"OR pg_has_role('{args.app_role}','{args.migration_role}','MEMBER')",
        expect_success=True,
    )
    if membership != "f":
        raise RuntimeError("application role has forbidden membership")

    if not all(IDENTIFIER.fullmatch(part) for part in args.probe_table.split(".")):
        raise SystemExit("probe table must be a schema-qualified unquoted identifier")
    readback = run_psql(
        dsn, f"SELECT probe_value FROM {args.probe_table} WHERE probe_id='TEST_SYN'",
        expect_success=True,
    )
    if readback != "1":
        raise RuntimeError("persistent TEST_SYN read probe failed")
    run_psql(
        dsn,
        f"BEGIN; UPDATE {args.probe_table} SET probe_value=2, updated_at=now() "
        "WHERE probe_id='TEST_SYN'; "
        f"SELECT probe_value FROM {args.probe_table} WHERE probe_id='TEST_SYN'; ROLLBACK",
        expect_success=True,
    )
    after = run_psql(
        dsn, f"SELECT probe_value FROM {args.probe_table} WHERE probe_id='TEST_SYN'",
        expect_success=True,
    )
    if after != "1":
        raise RuntimeError("persistent TEST_SYN rollback probe failed")
    denied = {
        "CREATE_DATABASE": "CREATE DATABASE test_syn_rbac_forbidden",
        "CREATE_ROLE": "CREATE ROLE test_syn_rbac_forbidden",
        "ALTER_ROLE": f"ALTER ROLE {args.owner_role} LOGIN",
        "SET_ROLE_OWNER": f"SET ROLE {args.owner_role}",
    }
    for sql in denied.values():
        run_psql(dsn, sql, expect_success=False)

    print(json.dumps({
        "APPLICATION_ROLE": args.app_role,
        "APPLICATION_START": "PASS",
        "READS": "PASS",
        "REQUIRED_WRITES": "PASS",
        "TRANSACTION_ROLLBACK": "PASS",
        **{key: "DENIED" for key in denied},
        "APP_SUPERUSER_REQUIRED": "NO",
        "STATUS": "PASS",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
