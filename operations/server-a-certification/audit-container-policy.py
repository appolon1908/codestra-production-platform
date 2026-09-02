#!/usr/bin/env python3
"""Fail-closed audit of production container reliability and immutable identity."""
from __future__ import annotations

import argparse
import json
import os
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

DEFAULT_POLICY = Path("/etc/codestra/server-a-certification/runtime-policy.json")
DEFAULT_EVIDENCE = Path(
    "/opt/codestra/evidence/server-a-certification/container-policy/LAST_RESULT.json"
)
DEFAULT_METRICS = Path(
    "/var/lib/node_exporter/textfile_collector/codestra_container_policy.prom"
)


def has_healthcheck(inspected: dict[str, Any]) -> bool:
    health = inspected.get("Config", {}).get("Healthcheck") or {}
    test = health.get("Test") or []
    return bool(test) and test != ["NONE"]


def has_cpu_limit(host: dict[str, Any]) -> bool:
    return int(host.get("NanoCpus") or 0) > 0 or (
        int(host.get("CpuQuota") or 0) > 0 and int(host.get("CpuPeriod") or 0) > 0
    )


def image_is_digest_pinned(inspected: dict[str, Any]) -> bool:
    reference = str(inspected.get("Config", {}).get("Image") or "")
    return re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", reference) is not None


def published_ports(inspected: dict[str, Any]) -> list[str]:
    bindings = inspected.get("HostConfig", {}).get("PortBindings") or {}
    values: list[str] = []
    for container_port, entries in bindings.items():
        for entry in entries or []:
            values.append(
                f"{entry.get('HostIp') or '0.0.0.0'}:{entry.get('HostPort') or '*'}->{container_port}"
            )
    return sorted(values)


def audit_item(item: dict[str, Any]) -> dict[str, Any]:
    inspected = resolve_compose_service(
        project=item["compose_project"], service=item["compose_service"]
    )
    host = inspected.get("HostConfig") or {}
    restart = (host.get("RestartPolicy") or {}).get("Name") or "no"
    memory = int(host.get("Memory") or 0)
    pids = int(host.get("PidsLimit") or 0)
    ports = published_ports(inspected)
    approved_ports = item.get("approved_published_ports", [])
    if not isinstance(approved_ports, list) or not all(isinstance(value, str) for value in approved_ports):
        raise ContractError(f"approved_published_ports must be a string list: {item.get('id')}")
    checks = {
        "healthcheck": has_healthcheck(inspected),
        "restart_policy": restart in {"always", "unless-stopped"},
        "memory_limit": memory > 0,
        "cpu_limit": has_cpu_limit(host),
        "pid_limit": pids > 0,
        "digest_pinned_image": image_is_digest_pinned(inspected),
        "published_ports": ports == sorted(approved_ports),
    }
    return {
        "id": item["id"],
        "compose_project": item["compose_project"],
        "compose_service": item["compose_service"],
        "container_id": inspected.get("Id", "")[:12],
        "container_name": str(inspected.get("Name", "")).lstrip("/"),
        "image_reference": inspected.get("Config", {}).get("Image"),
        "restart_policy": restart,
        "memory_limit_bytes": memory,
        "nano_cpus": int(host.get("NanoCpus") or 0),
        "cpu_quota": int(host.get("CpuQuota") or 0),
        "pid_limit": pids,
        "published_ports": ports,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def publish_metrics(path: Path, records: list[dict[str, Any]]) -> None:
    total = len(records)
    def coverage(key: str) -> float:
        if not total:
            return 0.0
        return 100.0 * sum(1 for record in records if record["checks"].get(key)) / total

    lines = [
        "# HELP codestra_critical_container_policy_coverage_percent Percentage of critical containers satisfying the complete policy.",
        "# TYPE codestra_critical_container_policy_coverage_percent gauge",
        f"codestra_critical_container_policy_coverage_percent {100.0 * sum(1 for r in records if r['status']=='PASS') / total if total else 0:.3f}",
        "# HELP codestra_critical_container_healthcheck_coverage_percent Healthcheck coverage for critical containers.",
        "# TYPE codestra_critical_container_healthcheck_coverage_percent gauge",
        f"codestra_critical_container_healthcheck_coverage_percent {coverage('healthcheck'):.3f}",
        "# HELP codestra_critical_container_resource_limit_coverage_percent CPU, memory, and PID limit coverage for critical containers.",
        "# TYPE codestra_critical_container_resource_limit_coverage_percent gauge",
        f"codestra_critical_container_resource_limit_coverage_percent {100.0 * sum(1 for r in records if r['checks']['memory_limit'] and r['checks']['cpu_limit'] and r['checks']['pid_limit']) / total if total else 0:.3f}",
        "# HELP codestra_critical_container_immutable_image_coverage_percent Digest-pinned image coverage for critical containers.",
        "# TYPE codestra_critical_container_immutable_image_coverage_percent gauge",
        f"codestra_critical_container_immutable_image_coverage_percent {coverage('digest_pinned_image'):.3f}",
    ]
    write_prometheus_textfile(path, lines)


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
        if policy.get("schema") != "codestra.server-a-runtime-policy.v1":
            raise ContractError("unsupported runtime policy schema")
        if policy.get("target_server") != "65.109.65.169":
            raise ContractError("runtime policy target must be Server A")
        items = policy.get("critical_services")
        if not isinstance(items, list) or not items:
            raise ContractError("runtime policy has no critical services")
        ids = [item.get("id") for item in items]
        if len(ids) != len(set(ids)):
            raise ContractError("runtime policy contains duplicate service ids")
        records = [audit_item(item) for item in items]
        passed = sum(record["status"] == "PASS" for record in records)
        status = "PASS" if passed == len(records) else "FAIL"
        payload = {
            "schema": "codestra.server-a-runtime-policy-result.v1",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "critical_service_count": len(records),
            "passing_service_count": passed,
            "policy_coverage_percent": round(100 * passed / len(records), 3),
            "records": records,
        }
        atomic_write_json(args.evidence, payload)
        publish_metrics(args.metrics, records)
        print(json.dumps(payload, sort_keys=True))
        return 0 if status == "PASS" else 1
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        try:
            publish_metrics(args.metrics, records)
            atomic_write_json(
                args.evidence,
                {
                    "schema": "codestra.server-a-runtime-policy-result.v1",
                    "status": "FAIL",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc)[:1000],
                    "records": records,
                },
            )
        except Exception:
            pass
        print(f"CONTAINER_POLICY=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
