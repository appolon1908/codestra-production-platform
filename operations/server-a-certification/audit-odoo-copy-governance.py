#!/usr/bin/env python3
"""Audit Odoo production-derived database governance and filestore binding."""
from __future__ import annotations

import argparse
import hashlib
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
    find_mount,
    load_json,
    resolve_compose_service,
    run_command,
    write_prometheus_textfile,
)

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,62}$")
DEFAULT_POLICY = Path("/etc/codestra/server-a-certification/odoo-copy-governance.json")
DEFAULT_EVIDENCE = Path(
    "/opt/codestra/evidence/server-a-certification/odoo-copy-governance/LAST_RESULT.json"
)
DEFAULT_METRICS = Path(
    "/var/lib/node_exporter/textfile_collector/codestra_odoo_copy_governance.prom"
)
ALLOWED_DISPOSITIONS = {
    "KEEP_ACTIVE", "KEEP_REQUIRED_RESTORE", "KEEP_AUDIT_OR_LEGAL",
    "ARCHIVE", "DELETE_APPROVED",
}


def identifier(value: Any, *, field: str) -> str:
    text = str(value)
    if not IDENTIFIER_RE.fullmatch(text):
        raise ContractError(f"{field} is not a safe identifier")
    return text


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def psql(
    container_id: str, *, os_user: str, login_user: str, database: str,
    sql: str, check: bool = True,
) -> str:
    result = run_command(
        [
            "docker", "exec", "--user", os_user, container_id,
            "psql", "-X", "-A", "-t", "-F", "\t", "-v", "ON_ERROR_STOP=1",
            "-U", login_user, "-d", database, "-c", sql,
        ],
        timeout=120,
        check=check,
    )
    return result.stdout.decode("utf-8", "replace").strip()


def inspect_database_binding(inspected: dict[str, Any], contract: dict[str, Any]) -> str:
    binding_type = contract.get("type")
    if binding_type == "environment":
        name = str(contract.get("name", ""))
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", name):
            raise ContractError("Odoo database environment selector is invalid")
        values = {}
        for item in inspected.get("Config", {}).get("Env") or []:
            key, separator, value = str(item).partition("=")
            if separator:
                values[key] = value
        observed = values.get(name, "")
    elif binding_type == "command_regex":
        pattern = str(contract.get("pattern", ""))
        if not pattern or len(pattern) > 512:
            raise ContractError("Odoo command binding pattern is invalid")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ContractError(f"Odoo command binding regex is invalid: {exc}") from exc
        config = inspected.get("Config") or {}
        command = " ".join(
            str(value) for value in [*(config.get("Entrypoint") or []), *(config.get("Cmd") or [])]
        )
        match = compiled.search(command)
        if not match or match.lastindex != 1:
            raise ContractError("Odoo command binding did not produce exactly one database capture")
        observed = match.group(1)
    else:
        raise ContractError("Odoo database binding type must be environment or command_regex")
    return identifier(observed, field="observed Odoo database")


def mount_source(mount: dict[str, Any]) -> str:
    if mount.get("Type") == "volume":
        value = str(mount.get("Name") or "")
    elif mount.get("Type") == "bind":
        value = str(mount.get("Source") or "")
    else:
        raise ContractError("Odoo filestore mount must be a named volume or bind mount")
    if not value:
        raise ContractError("Odoo filestore mount has no source identity")
    return value


def publish_metrics(path: Path, payload: dict[str, Any] | None) -> None:
    success = 1 if payload and payload.get("status") == "PASS" else 0
    count = int(payload.get("production_uuid_database_count", 0)) if payload else 0
    violations = len(payload.get("violations", [])) if payload else 1
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_odoo_copy_governance_success Whether Odoo copy disposition and filestore binding pass.",
            "# TYPE codestra_odoo_copy_governance_success gauge",
            f"codestra_odoo_copy_governance_success {success}",
            "# HELP codestra_odoo_production_uuid_database_count Databases sharing the production Odoo UUID.",
            "# TYPE codestra_odoo_production_uuid_database_count gauge",
            f"codestra_odoo_production_uuid_database_count {count}",
            "# HELP codestra_odoo_copy_governance_violations Odoo copy governance violations.",
            "# TYPE codestra_odoo_copy_governance_violations gauge",
            f"codestra_odoo_copy_governance_violations {violations}",
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
    payload: dict[str, Any] | None = None
    try:
        policy = load_json(args.policy)
        if policy.get("schema") != "codestra.server-a-odoo-copy-governance.v1":
            raise ContractError("unsupported Odoo copy governance schema")
        if policy.get("target_server") != "65.109.65.169":
            raise ContractError("Odoo copy governance target must be Server A")
        postgres = policy.get("postgres") or {}
        inspected_db = resolve_compose_service(
            project=postgres["compose_project"], service=postgres["compose_service"]
        )
        os_user = identifier(postgres.get("os_user", "postgres"), field="PostgreSQL OS user")
        login_user = identifier(postgres.get("admin_login_user"), field="PostgreSQL login user")
        maintenance = identifier(
            postgres.get("maintenance_database", "postgres"), field="maintenance database"
        )
        production_database = identifier(
            policy.get("production_database"), field="production Odoo database"
        )
        expected_count = int(policy.get("expected_production_uuid_database_count"))
        if expected_count < 1:
            raise ContractError("expected Odoo UUID database count must be positive")
        database_names = [
            line.strip()
            for line in psql(
                inspected_db["Id"],
                os_user=os_user,
                login_user=login_user,
                database=maintenance,
                sql=(
                    "select datname from pg_database where datallowconn and not datistemplate "
                    "order by datname"
                ),
            ).splitlines()
            if line.strip()
        ]
        if production_database not in database_names:
            raise ContractError("production Odoo database is not present")

        database_uuids: dict[str, str] = {}
        uuid_sql = (
            "select case when to_regclass('public.ir_config_parameter') is null then '' "
            "else coalesce((select value from public.ir_config_parameter "
            "where key='database.uuid' limit 1),'') end"
        )
        for database in database_names:
            safe_database = identifier(database, field="discovered database")
            value = psql(
                inspected_db["Id"],
                os_user=os_user,
                login_user=login_user,
                database=safe_database,
                sql=uuid_sql,
            )
            if value:
                if "\n" in value or "\t" in value or len(value) > 128:
                    raise ContractError(f"database {database} returned an invalid UUID value")
                database_uuids[database] = value
        production_uuid = database_uuids.get(production_database)
        if not production_uuid:
            raise ContractError("production Odoo database UUID is unavailable")
        derived = sorted(
            database for database, value in database_uuids.items() if value == production_uuid
        )

        configured_copies = policy.get("copies")
        if not isinstance(configured_copies, list) or not configured_copies:
            raise ContractError("Odoo copy disposition inventory is empty")
        copy_policy: dict[str, dict[str, Any]] = {}
        violations: list[dict[str, Any]] = []
        for item in configured_copies:
            database = identifier(item.get("database"), field="copy database")
            if database in copy_policy:
                raise ContractError(f"duplicate Odoo copy disposition for {database}")
            disposition = str(item.get("disposition", ""))
            if disposition not in ALLOWED_DISPOSITIONS:
                raise ContractError(f"unsupported Odoo copy disposition for {database}")
            environment = str(item.get("environment", ""))
            if environment not in {
                "production", "staging", "development", "test", "certification",
                "restore", "audit", "archive",
            }:
                raise ContractError(f"invalid Odoo environment classification for {database}")
            owner = str(item.get("owner", "")).strip()
            approved = item.get("approved") is True
            if not owner:
                raise ContractError(f"Odoo copy {database} has no responsible owner")
            if not approved:
                violations.append({"type": "copy_not_approved", "database": database})
            if disposition == "DELETE_APPROVED" and database in derived:
                violations.append(
                    {"type": "approved_deletion_database_still_present", "database": database}
                )
            copy_policy[database] = {
                "disposition": disposition,
                "environment": environment,
                "owner": owner,
                "approved": approved,
            }

        expected_set = set(copy_policy)
        actual_set = set(derived)
        for database in sorted(actual_set - expected_set):
            violations.append({"type": "unclassified_production_derived_copy", "database": database})
        for database in sorted(expected_set - actual_set):
            violations.append({"type": "configured_copy_not_matching_production_uuid", "database": database})
        if len(derived) != expected_count:
            violations.append(
                {
                    "type": "production_uuid_database_count",
                    "observed": len(derived),
                    "expected": expected_count,
                }
            )

        runtime_roles = [
            identifier(value, field="production Odoo runtime role")
            for value in policy.get("production_runtime_roles") or []
        ]
        if not runtime_roles:
            raise ContractError("production Odoo runtime role inventory is empty")
        connection_records: list[dict[str, Any]] = []
        for database in derived:
            if database == production_database:
                continue
            public_connect = psql(
                inspected_db["Id"],
                os_user=os_user,
                login_user=login_user,
                database=maintenance,
                sql=(
                    "select exists(select 1 from pg_database d,"
                    "lateral aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a "
                    f"where d.datname={literal(database)} and a.grantee=0 "
                    "and a.privilege_type='CONNECT')"
                ),
            ) == "t"
            if public_connect:
                violations.append({"type": "nonproduction_copy_public_connect", "database": database})
            for role in runtime_roles:
                observed = psql(
                    inspected_db["Id"],
                    os_user=os_user,
                    login_user=login_user,
                    database=maintenance,
                    sql=(
                        "select has_database_privilege("
                        f"{literal(role)},{literal(database)},'CONNECT')"
                    ),
                ) == "t"
                connection_records.append({"database": database, "role": role, "connect": observed})
                if observed:
                    violations.append(
                        {
                            "type": "production_role_can_connect_to_nonproduction_copy",
                            "database": database,
                            "role": role,
                        }
                    )

        active_raw = policy.get("active_environments")
        if not isinstance(active_raw, list) or not active_raw:
            raise ContractError("active Odoo runtime inventory is empty")
        active_records: list[dict[str, Any]] = []
        production_filestore_sources: set[str] = set()
        nonproduction_filestore_sources: set[str] = set()
        for item in active_raw:
            environment_id = identifier(item.get("id"), field="Odoo environment id")
            environment = str(item.get("environment", ""))
            if environment not in {"production", "staging", "development", "test", "certification"}:
                raise ContractError(f"active Odoo environment {environment_id} is invalid")
            expected_database = identifier(item.get("database"), field="expected Odoo database")
            inspected = resolve_compose_service(
                project=item["compose_project"], service=item["compose_service"]
            )
            observed_database = inspect_database_binding(
                inspected, item.get("database_binding") or {}
            )
            destination = str(item.get("filestore_mount_destination", ""))
            if not destination.startswith("/") or ".." in Path(destination).parts:
                raise ContractError(f"Odoo environment {environment_id} filestore destination is invalid")
            observed_filestore = mount_source(find_mount(inspected, destination))
            expected_filestore = str(item.get("expected_filestore_source", ""))
            if not expected_filestore:
                raise ContractError(f"Odoo environment {environment_id} has no filestore source contract")
            if observed_database != expected_database:
                violations.append(
                    {
                        "type": "odoo_database_binding_mismatch",
                        "environment": environment_id,
                        "observed": observed_database,
                        "expected": expected_database,
                    }
                )
            if observed_filestore != expected_filestore:
                violations.append(
                    {
                        "type": "odoo_filestore_binding_mismatch",
                        "environment": environment_id,
                        "observed": observed_filestore,
                        "expected": expected_filestore,
                    }
                )
            target_set = production_filestore_sources if environment == "production" else nonproduction_filestore_sources
            target_set.add(observed_filestore)
            active_records.append(
                {
                    "id": environment_id,
                    "environment": environment,
                    "database": observed_database,
                    "expected_database": expected_database,
                    "filestore_source": observed_filestore,
                    "expected_filestore_source": expected_filestore,
                    "container_id": inspected["Id"][:12],
                }
            )
        overlap = sorted(production_filestore_sources & nonproduction_filestore_sources)
        for source in overlap:
            violations.append({"type": "production_filestore_shared_with_nonproduction", "source": source})

        status = "PASS" if not violations else "FAIL"
        payload = {
            "schema": "codestra.server-a-odoo-copy-governance-result.v1",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_server": "65.109.65.169",
            "production_database": production_database,
            "production_uuid_sha256": hashlib.sha256(production_uuid.encode("utf-8")).hexdigest(),
            "production_uuid_database_count": len(derived),
            "production_uuid_databases": derived,
            "copy_dispositions": copy_policy,
            "connection_records": connection_records,
            "active_environments": active_records,
            "filestore_alignment": not any(
                item["type"].startswith("odoo_filestore")
                or item["type"] == "production_filestore_shared_with_nonproduction"
                for item in violations
            ),
            "violations": violations,
        }
        atomic_write_json(args.evidence, payload)
        publish_metrics(args.metrics, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if status == "PASS" else 1
    except (ContractError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        failure = {
            "schema": "codestra.server-a-odoo-copy-governance-result.v1",
            "status": "FAIL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_server": "65.109.65.169",
            "error": str(exc)[:1000],
        }
        try:
            atomic_write_json(args.evidence, failure)
            publish_metrics(args.metrics, payload)
        except Exception:
            pass
        print(f"ODOO_COPY_GOVERNANCE_AUDIT=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
