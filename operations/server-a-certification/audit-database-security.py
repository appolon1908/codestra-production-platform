#!/usr/bin/env python3
"""Audit PostgreSQL runtime-role privilege and CONNECT isolation contracts."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PACKAGE = Path(__file__).resolve().parents[1] / "database-certification"
sys.path.insert(0, str(DB_PACKAGE))
from runtime_contract import (  # noqa: E402
    ContractError,
    atomic_write_json,
    load_json,
    resolve_compose_service,
    run_command,
    write_prometheus_textfile,
)

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,62}$")
DEFAULT_POLICY = Path("/etc/codestra/server-a-certification/database-security.json")
DEFAULT_EVIDENCE = Path(
    "/opt/codestra/evidence/server-a-certification/database-security/LAST_RESULT.json"
)
DEFAULT_METRICS = Path(
    "/var/lib/node_exporter/textfile_collector/codestra_database_security.prom"
)


def identifier(value: Any, *, field: str) -> str:
    text = str(value)
    if not IDENTIFIER_RE.fullmatch(text):
        raise ContractError(f"{field} is not a safe PostgreSQL identifier")
    return text


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def psql(
    container_id: str,
    *,
    os_user: str,
    login_user: str,
    database: str,
    sql: str,
) -> str:
    result = run_command(
        [
            "docker", "exec", "--user", os_user, container_id,
            "psql", "-X", "-A", "-t", "-F", "\t", "-v", "ON_ERROR_STOP=1",
            "-U", login_user, "-d", database, "-c", sql,
        ],
        timeout=120,
    )
    return result.stdout.decode("utf-8", "replace").strip()


def rows(value: str) -> list[list[str]]:
    return [line.split("\t") for line in value.splitlines() if line.strip()]


def role_contract(item: dict[str, Any]) -> dict[str, Any]:
    name = identifier(item.get("name"), field="role name")
    classification = str(item.get("classification", ""))
    allowed_classes = {
        "runtime", "owner", "migration", "admin", "backup", "monitoring", "replication"
    }
    if classification not in allowed_classes:
        raise ContractError(f"unsupported role classification for {name}")
    allowed = item.get("allowed_databases")
    if not isinstance(allowed, list) or not allowed:
        raise ContractError(f"role {name} has no database allowlist")
    normalized = [
        "*" if database == "*" else identifier(database, field="allowed database")
        for database in allowed
    ]
    if "*" in normalized and len(normalized) != 1:
        raise ContractError(f"role {name} combines wildcard and explicit databases")
    return {"name": name, "classification": classification, "allowed_databases": normalized}


def audit_cluster(cluster: dict[str, Any]) -> dict[str, Any]:
    cluster_id = identifier(cluster.get("id"), field="cluster id")
    inspected = resolve_compose_service(
        project=cluster["compose_project"], service=cluster["compose_service"]
    )
    container_id = inspected["Id"]
    os_user = identifier(cluster.get("os_user", "postgres"), field="OS user")
    admin_login_user = identifier(cluster.get("admin_login_user"), field="admin login user")
    maintenance_database = identifier(
        cluster.get("maintenance_database", "postgres"), field="maintenance database"
    )
    configured_databases = cluster.get("databases")
    configured_roles = cluster.get("roles")
    if not isinstance(configured_databases, list) or not configured_databases:
        raise ContractError(f"cluster {cluster_id} has no database inventory")
    if not isinstance(configured_roles, list) or not configured_roles:
        raise ContractError(f"cluster {cluster_id} has no role inventory")

    database_policy: dict[str, dict[str, Any]] = {}
    for item in configured_databases:
        name = identifier(item.get("name"), field="database name")
        if name in database_policy:
            raise ContractError(f"cluster {cluster_id} duplicates database {name}")
        environment = str(item.get("environment", ""))
        if environment not in {
            "production", "staging", "development", "test", "certification", "restore", "system"
        }:
            raise ContractError(f"database {name} has an invalid environment classification")
        database_policy[name] = {
            "environment": environment,
            "public_connect_allowed": item.get("public_connect_allowed") is True,
        }

    role_policy: dict[str, dict[str, Any]] = {}
    for raw in configured_roles:
        item = role_contract(raw)
        if item["name"] in role_policy:
            raise ContractError(f"cluster {cluster_id} duplicates role {item['name']}")
        role_policy[item["name"]] = item

    actual_database_rows = rows(
        psql(
            container_id,
            os_user=os_user,
            login_user=admin_login_user,
            database=maintenance_database,
            sql=(
                "select datname,datallowconn from pg_database "
                "where not datistemplate order by datname"
            ),
        )
    )
    actual_databases = {name: allow == "t" for name, allow in actual_database_rows}
    actual_role_rows = rows(
        psql(
            container_id,
            os_user=os_user,
            login_user=admin_login_user,
            database=maintenance_database,
            sql=(
                "select rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,"
                "rolbypassrls,rolcanlogin from pg_roles "
                "where rolname !~ '^pg_' order by rolname"
            ),
        )
    )
    actual_roles = {
        row[0]: {
            "superuser": row[1] == "t",
            "createdb": row[2] == "t",
            "createrole": row[3] == "t",
            "replication": row[4] == "t",
            "bypassrls": row[5] == "t",
            "login": row[6] == "t",
        }
        for row in actual_role_rows
    }

    violations: list[dict[str, Any]] = []
    unclassified_databases = sorted(set(actual_databases) - set(database_policy))
    missing_databases = sorted(set(database_policy) - set(actual_databases))
    unclassified_roles = sorted(set(actual_roles) - set(role_policy))
    missing_roles = sorted(set(role_policy) - set(actual_roles))
    for value in unclassified_databases:
        violations.append({"type": "unclassified_database", "database": value})
    for value in missing_databases:
        violations.append({"type": "configured_database_missing", "database": value})
    for value in unclassified_roles:
        violations.append({"type": "unclassified_role", "role": value})
    for value in missing_roles:
        violations.append({"type": "configured_role_missing", "role": value})

    role_records: list[dict[str, Any]] = []
    for name, policy in sorted(role_policy.items()):
        attributes = actual_roles.get(name)
        role_violations: list[str] = []
        if attributes is not None and policy["classification"] == "runtime":
            for field in ("superuser", "createdb", "createrole", "replication", "bypassrls"):
                if attributes[field]:
                    role_violations.append(field)
                    violations.append(
                        {"type": "runtime_role_forbidden_attribute", "role": name, "attribute": field}
                    )
        role_records.append(
            {
                "role": name,
                "classification": policy["classification"],
                "attributes": attributes,
                "forbidden_runtime_attributes": role_violations,
            }
        )

    connect_records: list[dict[str, Any]] = []
    for database, db_policy in sorted(database_policy.items()):
        if database not in actual_databases:
            continue
        public_connect = psql(
            container_id,
            os_user=os_user,
            login_user=admin_login_user,
            database=maintenance_database,
            sql=(
                "select exists(select 1 from pg_database d, "
                "lateral aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a "
                f"where d.datname={literal(database)} and a.grantee=0 "
                "and a.privilege_type='CONNECT')"
            ),
        ) == "t"
        if public_connect != db_policy["public_connect_allowed"]:
            violations.append(
                {
                    "type": "public_connect_mismatch",
                    "database": database,
                    "observed": public_connect,
                    "expected": db_policy["public_connect_allowed"],
                }
            )
        for role, policy in sorted(role_policy.items()):
            if role not in actual_roles:
                continue
            expected = "*" in policy["allowed_databases"] or database in policy["allowed_databases"]
            observed = psql(
                container_id,
                os_user=os_user,
                login_user=admin_login_user,
                database=maintenance_database,
                sql=(
                    "select has_database_privilege("
                    f"{literal(role)},{literal(database)},'CONNECT')"
                ),
            ) == "t"
            connect_records.append(
                {"role": role, "database": database, "expected": expected, "observed": observed}
            )
            if observed != expected:
                violations.append(
                    {
                        "type": "database_connect_mismatch",
                        "role": role,
                        "database": database,
                        "observed": observed,
                        "expected": expected,
                    }
                )

    return {
        "id": cluster_id,
        "compose_project": cluster["compose_project"],
        "compose_service": cluster["compose_service"],
        "container_id": container_id[:12],
        "database_count": len(actual_databases),
        "role_count": len(actual_roles),
        "unclassified_databases": unclassified_databases,
        "unclassified_roles": unclassified_roles,
        "role_records": role_records,
        "connect_records": connect_records,
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }


def publish_metrics(path: Path, records: list[dict[str, Any]]) -> None:
    violations = sum(len(record.get("violations", [])) for record in records)
    runtime_superusers = sum(
        1
        for record in records
        for role in record.get("role_records", [])
        if role.get("classification") == "runtime"
        and role.get("attributes", {}).get("superuser")
    )
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_database_security_success Whether role and CONNECT isolation contracts pass.",
            "# TYPE codestra_database_security_success gauge",
            f"codestra_database_security_success {1 if records and violations == 0 else 0}",
            "# HELP codestra_database_security_violations Number of role/database isolation violations.",
            "# TYPE codestra_database_security_violations gauge",
            f"codestra_database_security_violations {violations}",
            "# HELP codestra_database_runtime_superusers Number of normal runtime roles that remain superuser.",
            "# TYPE codestra_database_runtime_superusers gauge",
            f"codestra_database_runtime_superusers {runtime_superusers}",
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records: list[dict[str, Any]] = []
    try:
        policy = load_json(args.policy)
        if policy.get("schema") != "codestra.server-a-database-security.v1":
            raise ContractError("unsupported database security policy schema")
        if policy.get("target_server") != "65.109.65.169":
            raise ContractError("database security policy target must be Server A")
        clusters = policy.get("clusters")
        if not isinstance(clusters, list) or not clusters:
            raise ContractError("database security policy has no clusters")
        records = [audit_cluster(cluster) for cluster in clusters]
        status = "PASS" if all(record["status"] == "PASS" for record in records) else "FAIL"
        payload = {
            "schema": "codestra.server-a-database-security-result.v1",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "clusters": records,
            "normal_application_superusers": sum(
                1
                for record in records
                for role in record["role_records"]
                if role["classification"] == "runtime"
                and role.get("attributes", {}).get("superuser")
            ),
            "violations": sum(len(record["violations"]) for record in records),
        }
        atomic_write_json(args.evidence, payload)
        publish_metrics(args.metrics, records)
        print(json.dumps(payload, sort_keys=True))
        return 0 if status == "PASS" else 1
    except (ContractError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        try:
            publish_metrics(args.metrics, records)
            atomic_write_json(
                args.evidence,
                {
                    "schema": "codestra.server-a-database-security-result.v1",
                    "status": "FAIL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc)[:1000],
                    "clusters": records,
                },
            )
        except Exception:
            pass
        print(f"DATABASE_SECURITY_AUDIT=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
