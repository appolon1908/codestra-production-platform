#!/usr/bin/env python3
"""Audit the realtime PostgreSQL primary/replica and routing-fence contract."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
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
    validate_protected_file,
    write_prometheus_textfile,
)

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,62}$")
DEFAULT_POLICY = Path("/etc/codestra/server-a-certification/realtime-ha.json")
DEFAULT_EVIDENCE = Path(
    "/opt/codestra/evidence/server-a-certification/realtime-ha/LAST_RESULT.json"
)
DEFAULT_METRICS = Path(
    "/var/lib/node_exporter/textfile_collector/codestra_realtime_ha.prom"
)


def identifier(value: Any, *, field: str) -> str:
    text = str(value)
    if not IDENTIFIER_RE.fullmatch(text):
        raise ContractError(f"{field} is not a safe PostgreSQL identifier")
    return text


def psql(
    container_id: str, *, os_user: str, login_user: str, database: str, sql: str
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


def one_row(value: str, *, columns: int, field: str) -> list[str]:
    rows = [line.split("\t") for line in value.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != columns:
        raise ContractError(f"unexpected {field} query shape")
    return rows[0]


def parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def routing_evidence(
    path: Path, *, expected_node_ids: list[str], max_age_hours: int
) -> dict[str, Any]:
    validate_protected_file(path)
    payload = load_json(path)
    if payload.get("schema") != "codestra.realtime-routing-fence-evidence.v1":
        raise ContractError("unsupported realtime routing evidence schema")
    if payload.get("status") != "PASS":
        raise ContractError("realtime routing evidence is not PASS")
    if payload.get("target_server") != "65.109.65.169":
        raise ContractError("realtime routing evidence targets another server")
    for field in (
        "false_standby_in_service_discovery",
        "false_standby_in_failover",
        "false_standby_in_routing",
    ):
        if payload.get(field) is not False:
            raise ContractError(f"realtime routing evidence does not fence {field}")
    valid = payload.get("valid_node_ids")
    if not isinstance(valid, list) or sorted(valid) != sorted(expected_node_ids):
        raise ContractError("routing evidence valid-node set does not match policy")
    owner = payload.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise ContractError("realtime routing evidence has no owner")
    verified_at = parse_timestamp(payload.get("verified_at"), field="verified_at")
    now = datetime.now(timezone.utc)
    if verified_at > now + timedelta(minutes=5):
        raise ContractError("realtime routing evidence is future dated")
    if now - verified_at > timedelta(hours=max_age_hours):
        raise ContractError("realtime routing evidence is stale")
    return {
        "status": "PASS",
        "verified_at": verified_at.isoformat(),
        "owner": owner,
        "valid_node_ids": sorted(valid),
    }


def node_config(item: dict[str, Any], *, field: str) -> dict[str, Any]:
    return {
        "id": identifier(item.get("id"), field=f"{field} id"),
        "compose_project": identifier(
            item.get("compose_project"), field=f"{field} compose project"
        ),
        "compose_service": identifier(
            item.get("compose_service"), field=f"{field} compose service"
        ),
        "os_user": identifier(item.get("os_user", "postgres"), field=f"{field} OS user"),
        "login_user": identifier(item.get("login_user"), field=f"{field} login user"),
        "database": identifier(item.get("database"), field=f"{field} database"),
        "max_receive_replay_lag_bytes": int(
            item.get("max_receive_replay_lag_bytes", 16 * 1024 * 1024)
        ),
    }


def inspect_primary(config: dict[str, Any]) -> dict[str, Any]:
    inspected = resolve_compose_service(
        project=config["compose_project"], service=config["compose_service"]
    )
    row = one_row(
        psql(
            inspected["Id"],
            os_user=config["os_user"],
            login_user=config["login_user"],
            database=config["database"],
            sql=(
                "select (pg_control_system()).system_identifier::text,"
                "pg_is_in_recovery(),current_setting('transaction_read_only'),"
                "(select count(*) from pg_stat_replication where state='streaming')"
            ),
        ),
        columns=4,
        field="primary",
    )
    system_identifier, recovery, read_only, streaming_count = row
    violations: list[str] = []
    if recovery != "f":
        violations.append("primary_is_in_recovery")
    if read_only != "off":
        violations.append("primary_is_read_only")
    try:
        streaming = int(streaming_count)
    except ValueError as exc:
        raise ContractError("primary streaming replica count is invalid") from exc
    return {
        "id": config["id"],
        "container_id": inspected["Id"][:12],
        "system_identifier": system_identifier,
        "in_recovery": recovery == "t",
        "transaction_read_only": read_only,
        "streaming_replica_count": streaming,
        "violations": violations,
    }


def inspect_replica(config: dict[str, Any]) -> dict[str, Any]:
    inspected = resolve_compose_service(
        project=config["compose_project"], service=config["compose_service"]
    )
    row = one_row(
        psql(
            inspected["Id"],
            os_user=config["os_user"],
            login_user=config["login_user"],
            database=config["database"],
            sql=(
                "select (pg_control_system()).system_identifier::text,"
                "pg_is_in_recovery(),current_setting('transaction_read_only'),"
                "exists(select 1 from pg_stat_wal_receiver where status='streaming'),"
                "pg_last_wal_receive_lsn() is not null,"
                "pg_last_wal_replay_lsn() is not null,"
                "coalesce(pg_wal_lsn_diff(pg_last_wal_receive_lsn(),"
                "pg_last_wal_replay_lsn())::bigint,0)"
            ),
        ),
        columns=7,
        field=f"replica {config['id']}",
    )
    (
        system_identifier, recovery, read_only, receiving,
        receive_lsn, replay_lsn, lag_text,
    ) = row
    try:
        lag = int(lag_text)
    except ValueError as exc:
        raise ContractError(f"replica {config['id']} lag is invalid") from exc
    violations: list[str] = []
    if recovery != "t":
        violations.append("not_in_recovery")
    if read_only != "on":
        violations.append("not_read_only")
    if receiving != "t":
        violations.append("wal_receiver_not_streaming")
    if receive_lsn != "t" or replay_lsn != "t":
        violations.append("receive_or_replay_lsn_missing")
    if lag < 0 or lag > config["max_receive_replay_lag_bytes"]:
        violations.append("receive_replay_lag_exceeds_policy")
    return {
        "id": config["id"],
        "container_id": inspected["Id"][:12],
        "system_identifier": system_identifier,
        "in_recovery": recovery == "t",
        "transaction_read_only": read_only,
        "wal_receiver_streaming": receiving == "t",
        "receive_lsn_present": receive_lsn == "t",
        "replay_lsn_present": replay_lsn == "t",
        "receive_replay_lag_bytes": lag,
        "max_receive_replay_lag_bytes": config["max_receive_replay_lag_bytes"],
        "violations": violations,
    }


def publish_metrics(path: Path, payload: dict[str, Any] | None) -> None:
    success = 1 if payload and payload.get("status") == "PASS" else 0
    replica_count = len(payload.get("replicas", [])) if payload else 0
    max_lag = max(
        [int(item.get("receive_replay_lag_bytes", 0)) for item in payload.get("replicas", [])],
        default=0,
    ) if payload else 0
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_realtime_ha_success Whether primary, replicas, and routing fences pass.",
            "# TYPE codestra_realtime_ha_success gauge",
            f"codestra_realtime_ha_success {success}",
            "# HELP codestra_realtime_valid_replicas Number of configured replicas inspected.",
            "# TYPE codestra_realtime_valid_replicas gauge",
            f"codestra_realtime_valid_replicas {replica_count if success else 0}",
            "# HELP codestra_realtime_replica_max_receive_replay_lag_bytes Maximum inspected receive/replay lag.",
            "# TYPE codestra_realtime_replica_max_receive_replay_lag_bytes gauge",
            f"codestra_realtime_replica_max_receive_replay_lag_bytes {max_lag}",
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
        if policy.get("schema") != "codestra.server-a-realtime-ha.v1":
            raise ContractError("unsupported realtime HA policy schema")
        if policy.get("target_server") != "65.109.65.169":
            raise ContractError("realtime HA policy target must be Server A")
        primary = node_config(policy.get("primary") or {}, field="primary")
        replicas_raw = policy.get("replicas")
        if not isinstance(replicas_raw, list) or not replicas_raw:
            raise ContractError("at least one expected realtime replica is required")
        replicas = [node_config(item, field="replica") for item in replicas_raw]
        ids = [primary["id"], *[item["id"] for item in replicas]]
        if len(ids) != len(set(ids)):
            raise ContractError("realtime node ids must be unique")
        inspected_primary = inspect_primary(primary)
        inspected_replicas = [inspect_replica(item) for item in replicas]
        container_ids = [
            inspected_primary["container_id"], *[item["container_id"] for item in inspected_replicas]
        ]
        violations: list[dict[str, Any]] = []
        if len(container_ids) != len(set(container_ids)):
            violations.append({"type": "duplicate_runtime_container"})
        for value in inspected_primary["violations"]:
            violations.append({"type": "primary_state", "detail": value})
        for replica in inspected_replicas:
            if replica["system_identifier"] != inspected_primary["system_identifier"]:
                violations.append(
                    {"type": "system_identifier_mismatch", "replica": replica["id"]}
                )
            for value in replica["violations"]:
                violations.append(
                    {"type": "replica_state", "replica": replica["id"], "detail": value}
                )
        if inspected_primary["streaming_replica_count"] < len(inspected_replicas):
            violations.append(
                {
                    "type": "primary_streaming_replica_count",
                    "observed": inspected_primary["streaming_replica_count"],
                    "minimum": len(inspected_replicas),
                }
            )
        max_age_hours = int(policy.get("routing_evidence_max_age_hours", 24))
        if max_age_hours < 1 or max_age_hours > 168:
            raise ContractError("routing evidence max age must be between 1 and 168 hours")
        routing = routing_evidence(
            Path(str(policy.get("routing_evidence_file", ""))),
            expected_node_ids=ids,
            max_age_hours=max_age_hours,
        )
        status = "PASS" if not violations else "FAIL"
        payload = {
            "schema": "codestra.server-a-realtime-ha-result.v1",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_server": "65.109.65.169",
            "primary": inspected_primary,
            "replicas": inspected_replicas,
            "routing_fence": routing,
            "false_standby_removed": routing["status"] == "PASS",
            "violations": violations,
        }
        atomic_write_json(args.evidence, payload)
        publish_metrics(args.metrics, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if status == "PASS" else 1
    except (ContractError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        failure = {
            "schema": "codestra.server-a-realtime-ha-result.v1",
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
        print(f"REALTIME_HA_AUDIT=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
