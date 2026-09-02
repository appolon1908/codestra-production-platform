#!/usr/bin/env python3
"""Prove production/non-production network, volume, and secret isolation."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PACKAGE = Path(__file__).resolve().parents[1] / "database-certification"
sys.path.insert(0, str(DB_PACKAGE))
from runtime_contract import (  # noqa: E402
    ContractError,
    atomic_write_json,
    load_json,
    run_command,
    write_prometheus_textfile,
)

DEFAULT_POLICY = Path("/etc/codestra/server-a-certification/environment-isolation.json")
DEFAULT_EVIDENCE = Path(
    "/opt/codestra/evidence/server-a-certification/environment-isolation/LAST_RESULT.json"
)
DEFAULT_METRICS = Path(
    "/var/lib/node_exporter/textfile_collector/codestra_environment_isolation.prom"
)


def inspect_running() -> list[dict[str, Any]]:
    ids = run_command(["docker", "ps", "-q"], timeout=30).stdout.decode().splitlines()
    ids = [value.strip() for value in ids if value.strip()]
    if not ids:
        raise ContractError("no running Docker containers were found")
    payload = json.loads(run_command(["docker", "inspect", *ids], timeout=120).stdout)
    if not isinstance(payload, list) or len(payload) != len(ids):
        raise ContractError("Docker inspect returned an incomplete running-container inventory")
    return payload


def classify(project: str, policy: dict[str, Any]) -> str:
    if project in set(policy.get("production_projects", [])):
        return "production"
    patterns = policy.get("nonproduction_project_patterns", [])
    if any(re.search(pattern, project) for pattern in patterns):
        return "nonproduction"
    return "unclassified"


def container_record(inspected: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    labels = inspected.get("Config", {}).get("Labels") or {}
    project = labels.get("com.docker.compose.project") or ""
    service = labels.get("com.docker.compose.service") or ""
    environment = classify(project, policy)
    networks = sorted((inspected.get("NetworkSettings", {}).get("Networks") or {}).keys())
    network_mode = str((inspected.get("HostConfig") or {}).get("NetworkMode") or "")
    mounts = []
    for mount in inspected.get("Mounts") or []:
        mounts.append(
            {
                "type": mount.get("Type"),
                "name": mount.get("Name"),
                "source": mount.get("Source"),
                "destination": mount.get("Destination"),
                "rw": bool(mount.get("RW")),
            }
        )
    return {
        "container_id": inspected.get("Id", "")[:12],
        "container_name": str(inspected.get("Name", "")).lstrip("/"),
        "compose_project": project,
        "compose_service": service,
        "environment": environment,
        "networks": networks,
        "network_mode": network_mode,
        "mounts": mounts,
    }


def cross_environment_violations(records: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    allowed_networks = set(policy.get("shared_network_allowlist", []))
    allowed_mounts = set(policy.get("shared_mount_source_allowlist", []))
    network_usage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mount_usage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["environment"] not in {"production", "nonproduction"}:
            continue
        for network in record["networks"]:
            if network not in {"bridge", "host", "none"}:
                network_usage[network].append(record)
        for mount in record["mounts"]:
            source = mount.get("source") or mount.get("name")
            if source:
                mount_usage[str(source)].append(record)
    violations: list[dict[str, Any]] = []
    for network, users in sorted(network_usage.items()):
        environments = {user["environment"] for user in users}
        if environments == {"production", "nonproduction"} and network not in allowed_networks:
            violations.append(
                {
                    "type": "shared_network",
                    "resource": network,
                    "containers": sorted(user["container_name"] for user in users),
                }
            )
    for source, users in sorted(mount_usage.items()):
        environments = {user["environment"] for user in users}
        if environments == {"production", "nonproduction"} and source not in allowed_mounts:
            violations.append(
                {
                    "type": "shared_cross_environment_mount",
                    "resource": source,
                    "containers": sorted(user["container_name"] for user in users),
                    "write_access": sorted(
                        user["container_name"]
                        for user in users
                        if any(
                            (mount.get("source") or mount.get("name")) == source and mount.get("rw")
                            for mount in user["mounts"]
                        )
                    ),
                }
            )
    for record in records:
        mode = record.get("network_mode", "")
        if record["environment"] == "nonproduction" and (
            mode == "host" or mode.startswith("container:")
        ):
            violations.append(
                {
                    "type": "nonproduction_unisolated_network_mode",
                    "resource": mode,
                    "containers": [record["container_name"]],
                }
            )
    return violations


def secret_mount_violations(records: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    protected_prefixes = [str(value).rstrip("/") for value in policy.get("production_secret_source_prefixes", [])]
    violations: list[dict[str, Any]] = []
    for record in records:
        if record["environment"] != "nonproduction":
            continue
        for mount in record["mounts"]:
            source = str(mount.get("source") or "")
            if any(source == prefix or source.startswith(prefix + "/") for prefix in protected_prefixes):
                violations.append(
                    {
                        "type": "production_secret_mounted_in_nonproduction",
                        "resource": source,
                        "container": record["container_name"],
                        "destination": mount.get("destination"),
                    }
                )
    return violations


def publish_metrics(path: Path, *, status: str, violations: int, unclassified: int) -> None:
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_environment_isolation_success Whether network, writable-volume, and production-secret isolation passed.",
            "# TYPE codestra_environment_isolation_success gauge",
            f"codestra_environment_isolation_success {1 if status == 'PASS' else 0}",
            "# HELP codestra_environment_isolation_violations Number of detected cross-environment violations.",
            "# TYPE codestra_environment_isolation_violations gauge",
            f"codestra_environment_isolation_violations {violations}",
            "# HELP codestra_environment_unclassified_containers Number of running containers whose environment is unclassified.",
            "# TYPE codestra_environment_unclassified_containers gauge",
            f"codestra_environment_unclassified_containers {unclassified}",
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
    try:
        policy = load_json(args.policy)
        if policy.get("schema") != "codestra.server-a-environment-isolation.v1":
            raise ContractError("unsupported environment isolation policy schema")
        if policy.get("target_server") != "65.109.65.169":
            raise ContractError("environment isolation target must be Server A")
        production_projects = policy.get("production_projects")
        if not isinstance(production_projects, list) or not production_projects:
            raise ContractError("production project inventory is empty")
        patterns = policy.get("nonproduction_project_patterns")
        if not isinstance(patterns, list) or not patterns:
            raise ContractError("nonproduction project patterns are empty")
        try:
            for pattern in patterns:
                re.compile(str(pattern))
        except re.error as exc:
            raise ContractError(f"invalid nonproduction project pattern: {exc}") from exc
        records = [container_record(item, policy) for item in inspect_running()]
        violations = cross_environment_violations(records, policy)
        violations.extend(secret_mount_violations(records, policy))
        unclassified = [record for record in records if record["environment"] == "unclassified"]
        status = "PASS" if not violations and not unclassified else "FAIL"
        payload = {
            "schema": "codestra.server-a-environment-isolation-result.v1",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "running_container_count": len(records),
            "unclassified_container_count": len(unclassified),
            "unclassified_containers": [record["container_name"] for record in unclassified],
            "violations": violations,
            "records": records,
        }
        atomic_write_json(args.evidence, payload)
        publish_metrics(
            args.metrics,
            status=status,
            violations=len(violations),
            unclassified=len(unclassified),
        )
        print(json.dumps(payload, sort_keys=True))
        return 0 if status == "PASS" else 1
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        try:
            publish_metrics(args.metrics, status="FAIL", violations=1, unclassified=1)
            atomic_write_json(
                args.evidence,
                {
                    "schema": "codestra.server-a-environment-isolation-result.v1",
                    "status": "FAIL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc)[:1000],
                },
            )
        except Exception:
            pass
        print(f"ENVIRONMENT_ISOLATION=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
