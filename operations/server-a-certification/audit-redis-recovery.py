#!/usr/bin/env python3
"""Audit production Redis classification, persistence, and recovery proof."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
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

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
ALLOWED_CLASSIFICATIONS = {
    "CACHE", "SESSION", "QUEUE_OR_BROKER", "RATE_LIMIT", "LOCKING",
    "JOB_STATE", "DURABLE_STATE", "WEBSOCKET_STATE",
}
ALLOWED_DECISIONS = {
    "TESTED_RECOVERY",
    "FORMALLY_DOCUMENTED_SAFE_LOSS_AND_REBUILD",
}
DEFAULT_POLICY = Path("/etc/codestra/server-a-certification/redis-recovery.json")
DEFAULT_EVIDENCE = Path(
    "/opt/codestra/evidence/server-a-certification/redis-recovery/LAST_RESULT.json"
)
DEFAULT_METRICS = Path(
    "/var/lib/node_exporter/textfile_collector/codestra_redis_recovery.prom"
)


def safe_id(value: Any, *, field: str) -> str:
    text = str(value)
    if not SAFE_ID_RE.fullmatch(text):
        raise ContractError(f"{field} contains unsupported characters")
    return text


def safe_container_path(value: Any, *, field: str) -> str:
    text = str(value)
    path = PurePosixPath(text)
    if not text.startswith("/") or ".." in path.parts or any(
        part in ("", ".") for part in path.parts[1:]
    ):
        raise ContractError(f"{field} must be an absolute traversal-free container path")
    if any("\n" in part or "\r" in part for part in path.parts):
        raise ContractError(f"{field} contains a newline")
    return text


def parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def redis_command(
    container_id: str, command: list[str], *, secret_path: str | None, username: str | None
) -> str:
    for value in command:
        if not isinstance(value, str) or "\x00" in value or "\n" in value or "\r" in value:
            raise ContractError("Redis command contains unsupported input")
    if secret_path:
        path = safe_container_path(secret_path, field="Redis password secret path")
        user_args = [] if not username else ["--user", safe_id(username, field="Redis ACL user")]
        result = run_command(
            [
                "docker", "exec", container_id, "sh", "-eu", "-c",
                'test -r "$1"; export REDISCLI_AUTH="$(cat "$1")"; shift; exec redis-cli --no-auth-warning --raw "$@"',
                "redis-audit", path, *user_args, *command,
            ],
            timeout=30,
        )
    else:
        args = ["docker", "exec", container_id, "redis-cli", "--raw"]
        if username:
            args.extend(["--user", safe_id(username, field="Redis ACL user")])
        result = run_command([*args, *command], timeout=30)
    return result.stdout.decode("utf-8", "replace").strip()


def config_value(
    container_id: str, key: str, *, secret_path: str | None, username: str | None
) -> str:
    output = redis_command(
        container_id, ["CONFIG", "GET", key], secret_path=secret_path, username=username
    ).splitlines()
    if len(output) != 2 or output[0] != key:
        raise ContractError(f"Redis CONFIG GET {key} returned an unexpected response")
    return output[1]


def recovery_evidence(
    path: Path, *, instance_id: str, decision: str, max_age_days: int
) -> dict[str, Any]:
    validate_protected_file(path)
    payload = load_json(path)
    if payload.get("schema") != "codestra.redis-recovery-evidence.v1":
        raise ContractError(f"Redis {instance_id} has an unsupported recovery evidence schema")
    if payload.get("status") != "PASS" or payload.get("target_server") != "65.109.65.169":
        raise ContractError(f"Redis {instance_id} recovery evidence is not PASS for Server A")
    if payload.get("instance_id") != instance_id or payload.get("decision") != decision:
        raise ContractError(f"Redis {instance_id} recovery evidence identity/decision mismatch")
    verified_at = parse_timestamp(payload.get("verified_at"), field="Redis verified_at")
    now = datetime.now(timezone.utc)
    if verified_at > now + timedelta(minutes=5):
        raise ContractError(f"Redis {instance_id} recovery evidence is future dated")
    if now - verified_at > timedelta(days=max_age_days):
        raise ContractError(f"Redis {instance_id} recovery evidence is stale")
    owner = str(payload.get("owner", "")).strip()
    if not owner:
        raise ContractError(f"Redis {instance_id} recovery evidence has no owner")
    if decision == "TESTED_RECOVERY":
        required = {
            "isolated_restore_status": "PASS",
            "dependent_service_reconnect": "PASS",
            "unsafe_job_replay": False,
            "duplicate_external_actions": 0,
        }
    else:
        required = {
            "postgres_durable_authority_verified": True,
            "rebuild_test_status": "PASS",
            "unsafe_job_replay": False,
            "duplicate_external_actions": 0,
        }
    for field, expected in required.items():
        if payload.get(field) != expected:
            raise ContractError(
                f"Redis {instance_id} recovery evidence field {field} is not {expected!r}"
            )
    return {
        "status": "PASS",
        "decision": decision,
        "verified_at": verified_at.isoformat(),
        "owner": owner,
    }


def inspect_instance(item: dict[str, Any], *, max_age_days: int) -> dict[str, Any]:
    instance_id = safe_id(item.get("id"), field="Redis instance id")
    classifications_raw = item.get("classifications")
    if not isinstance(classifications_raw, list) or not classifications_raw:
        raise ContractError(f"Redis {instance_id} has no classification")
    classifications = {str(value) for value in classifications_raw}
    if not classifications <= ALLOWED_CLASSIFICATIONS:
        raise ContractError(f"Redis {instance_id} has an unsupported classification")
    decision = str(item.get("decision", ""))
    if decision not in ALLOWED_DECISIONS:
        raise ContractError(f"Redis {instance_id} has no approved recovery decision")
    if "DURABLE_STATE" in classifications and decision != "TESTED_RECOVERY":
        raise ContractError(f"Redis {instance_id} is durable but lacks tested recovery")
    inspected = resolve_compose_service(
        project=item["compose_project"], service=item["compose_service"]
    )
    secret_path_value = item.get("password_secret_path")
    secret_path = None if not secret_path_value else safe_container_path(
        secret_path_value, field="Redis password secret path"
    )
    username_value = item.get("username")
    username = None if not username_value else safe_id(username_value, field="Redis ACL user")
    ping = redis_command(inspected["Id"], ["PING"], secret_path=secret_path, username=username)
    if ping != "PONG":
        raise ContractError(f"Redis {instance_id} did not return PONG")
    dbsize_text = redis_command(
        inspected["Id"], ["DBSIZE"], secret_path=secret_path, username=username
    )
    try:
        key_count = int(dbsize_text)
    except ValueError as exc:
        raise ContractError(f"Redis {instance_id} DBSIZE is invalid") from exc
    selected = {
        key: config_value(inspected["Id"], key, secret_path=secret_path, username=username)
        for key in ("appendonly", "appendfsync", "save", "maxmemory-policy")
    }
    expected_config = item.get("expected_config") or {}
    if not isinstance(expected_config, dict) or not expected_config:
        raise ContractError(f"Redis {instance_id} expected configuration is empty")
    violations: list[dict[str, str]] = []
    for key, expected in expected_config.items():
        if key not in selected:
            raise ContractError(f"Redis {instance_id} policy contains unsupported CONFIG key {key}")
        if selected[key] != str(expected):
            violations.append(
                {
                    "type": "configuration_mismatch",
                    "key": key,
                    "observed": selected[key],
                    "expected": str(expected),
                }
            )
    info = redis_command(
        inspected["Id"], ["INFO", "persistence"], secret_path=secret_path, username=username
    )
    persistence: dict[str, str] = {}
    for line in info.splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        if key in {
            "loading", "rdb_last_bgsave_status", "aof_enabled",
            "aof_last_bgrewrite_status", "aof_last_write_status",
        }:
            persistence[key] = value
    if persistence.get("loading") not in {None, "0"}:
        violations.append({"type": "redis_loading", "observed": persistence["loading"]})
    if selected["appendonly"] == "yes":
        for key in ("aof_enabled", "aof_last_bgrewrite_status", "aof_last_write_status"):
            expected = "1" if key == "aof_enabled" else "ok"
            if persistence.get(key) not in {None, expected}:
                violations.append(
                    {
                        "type": "aof_persistence_status",
                        "key": key,
                        "observed": persistence.get(key, "missing"),
                    }
                )
    evidence = recovery_evidence(
        Path(str(item.get("evidence_file", ""))),
        instance_id=instance_id,
        decision=decision,
        max_age_days=max_age_days,
    )
    return {
        "id": instance_id,
        "container_id": inspected["Id"][:12],
        "classifications": sorted(classifications),
        "decision": decision,
        "key_count": key_count,
        "configuration": selected,
        "persistence": persistence,
        "recovery_evidence": evidence,
        "violations": violations,
        "status": "PASS" if not violations else "FAIL",
    }


def publish_metrics(path: Path, payload: dict[str, Any] | None) -> None:
    success = 1 if payload and payload.get("status") == "PASS" else 0
    instances = len(payload.get("instances", [])) if payload else 0
    violations = len(payload.get("violations", [])) if payload else 1
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_redis_recovery_contract_success Whether Redis classification and recovery evidence pass.",
            "# TYPE codestra_redis_recovery_contract_success gauge",
            f"codestra_redis_recovery_contract_success {success}",
            "# HELP codestra_redis_recovery_instances Number of classified production Redis instances.",
            "# TYPE codestra_redis_recovery_instances gauge",
            f"codestra_redis_recovery_instances {instances}",
            "# HELP codestra_redis_recovery_violations Number of Redis recovery/configuration violations.",
            "# TYPE codestra_redis_recovery_violations gauge",
            f"codestra_redis_recovery_violations {violations}",
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
        if policy.get("schema") != "codestra.server-a-redis-recovery.v1":
            raise ContractError("unsupported Redis recovery policy schema")
        if policy.get("target_server") != "65.109.65.169":
            raise ContractError("Redis recovery policy target must be Server A")
        max_age_days = int(policy.get("evidence_max_age_days", 90))
        if max_age_days < 1 or max_age_days > 365:
            raise ContractError("Redis evidence max age must be between 1 and 365 days")
        raw_instances = policy.get("instances")
        if not isinstance(raw_instances, list) or not raw_instances:
            raise ContractError("Redis recovery policy has no production instances")
        instances = [inspect_instance(item, max_age_days=max_age_days) for item in raw_instances]
        ids = [item["id"] for item in instances]
        if len(ids) != len(set(ids)):
            raise ContractError("Redis instance ids must be unique")
        violations = [
            {"instance": item["id"], **violation}
            for item in instances
            for violation in item["violations"]
        ]
        status = "PASS" if all(item["status"] == "PASS" for item in instances) else "FAIL"
        payload = {
            "schema": "codestra.server-a-redis-recovery-result.v1",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_server": "65.109.65.169",
            "instances": instances,
            "decisions": {item["id"]: item["decision"] for item in instances},
            "violations": violations,
            "key_values_exported": False,
            "production_business_writes_executed": False,
        }
        atomic_write_json(args.evidence, payload)
        publish_metrics(args.metrics, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if status == "PASS" else 1
    except (ContractError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        failure = {
            "schema": "codestra.server-a-redis-recovery-result.v1",
            "status": "FAIL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_server": "65.109.65.169",
            "error": str(exc)[:1000],
            "key_values_exported": False,
        }
        try:
            atomic_write_json(args.evidence, failure)
            publish_metrics(args.metrics, payload)
        except Exception:
            pass
        print(f"REDIS_RECOVERY_AUDIT=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
