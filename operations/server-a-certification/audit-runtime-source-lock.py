#!/usr/bin/env python3
"""Compare every running Server A Compose workload to an exact source lock."""
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
    require_digest_image,
    run_command,
    write_prometheus_textfile,
)

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HTTPS_REPOSITORY_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DEFAULT_POLICY = Path("/etc/codestra/server-a-certification/runtime-source-lock.json")
DEFAULT_EVIDENCE = Path(
    "/opt/codestra/evidence/server-a-certification/runtime-source-lock/LAST_RESULT.json"
)
DEFAULT_METRICS = Path(
    "/var/lib/node_exporter/textfile_collector/codestra_runtime_source_lock.prom"
)


def safe_id(value: Any, *, field: str) -> str:
    text = str(value)
    if not SAFE_ID_RE.fullmatch(text):
        raise ContractError(f"{field} contains unsupported characters")
    return text


def load_policy(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load runtime source lock: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("runtime source lock must be a JSON object")
    if payload.get("schema") != "codestra.server-a-runtime-source-lock.v1":
        raise ContractError("unsupported runtime source lock schema")
    if payload.get("target_server") != "65.109.65.169":
        raise ContractError("runtime source lock target must be Server A")
    return payload


def inspect_running() -> list[dict[str, Any]]:
    ids = [
        value.strip()
        for value in run_command(["docker", "ps", "-q"], timeout=30).stdout.decode().splitlines()
        if value.strip()
    ]
    if not ids:
        raise ContractError("no running Docker containers were found")
    payload = json.loads(run_command(["docker", "inspect", *ids], timeout=180).stdout)
    if not isinstance(payload, list) or len(payload) != len(ids):
        raise ContractError("Docker inspect returned an incomplete runtime inventory")
    return payload


def workload_contract(item: dict[str, Any]) -> dict[str, Any]:
    workload_id = safe_id(item.get("id"), field="workload id")
    project = safe_id(item.get("compose_project"), field=f"{workload_id} project")
    service = safe_id(item.get("compose_service"), field=f"{workload_id} service")
    environment = str(item.get("environment", ""))
    if environment not in {"production", "staging", "development", "test", "certification", "restore"}:
        raise ContractError(f"{workload_id} has an invalid environment")
    source_type = str(item.get("source_type", ""))
    if source_type not in {"github", "vendor"}:
        raise ContractError(f"{workload_id} source_type must be github or vendor")
    image = require_digest_image(str(item.get("image", "")), field=f"{workload_id} image")
    rollback_image = require_digest_image(
        str(item.get("rollback_image", "")), field=f"{workload_id} rollback image"
    )
    expected_instances = int(item.get("expected_instances", 1))
    if expected_instances < 1 or expected_instances > 100:
        raise ContractError(f"{workload_id} expected_instances is invalid")
    source_reference = str(item.get("source_reference", "")).strip()
    revision = str(item.get("revision", "")).strip()
    if source_type == "github":
        if not HTTPS_REPOSITORY_RE.fullmatch(source_reference):
            raise ContractError(f"{workload_id} GitHub source_reference is invalid")
        if not SHA_RE.fullmatch(revision):
            raise ContractError(f"{workload_id} revision must be an exact commit")
    else:
        if not source_reference or len(source_reference) > 200 or "\n" in source_reference:
            raise ContractError(f"{workload_id} vendor source_reference is invalid")
        if revision != "N/A_VENDOR":
            raise ContractError(f"{workload_id} vendor revision must be N/A_VENDOR")
    return {
        "id": workload_id,
        "compose_project": project,
        "compose_service": service,
        "environment": environment,
        "source_type": source_type,
        "source_reference": source_reference,
        "revision": revision,
        "image": image,
        "rollback_image": rollback_image,
        "expected_instances": expected_instances,
        "critical": item.get("critical") is True,
    }


def publish_metrics(path: Path, payload: dict[str, Any] | None) -> None:
    success = 1 if payload and payload.get("status") == "PASS" else 0
    unknown = int(payload.get("unknown_runtime_components", 1)) if payload else 1
    mismatches = int(payload.get("mismatch_count", 1)) if payload else 1
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_runtime_source_lock_success Whether all running workloads match exact source/image locks.",
            "# TYPE codestra_runtime_source_lock_success gauge",
            f"codestra_runtime_source_lock_success {success}",
            "# HELP codestra_runtime_source_lock_unknown_components Running components absent from the source lock.",
            "# TYPE codestra_runtime_source_lock_unknown_components gauge",
            f"codestra_runtime_source_lock_unknown_components {unknown}",
            "# HELP codestra_runtime_source_lock_mismatches Runtime/source/image mismatches.",
            "# TYPE codestra_runtime_source_lock_mismatches gauge",
            f"codestra_runtime_source_lock_mismatches {mismatches}",
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
        policy = load_policy(args.policy)
        raw_workloads = policy.get("workloads")
        if not isinstance(raw_workloads, list) or not raw_workloads:
            raise ContractError("runtime source lock has no workloads")
        contracts = [workload_contract(item) for item in raw_workloads]
        ids = [item["id"] for item in contracts]
        keys = [(item["compose_project"], item["compose_service"]) for item in contracts]
        if len(ids) != len(set(ids)):
            raise ContractError("runtime source lock workload ids must be unique")
        if len(keys) != len(set(keys)):
            raise ContractError("runtime source lock Compose project/service keys must be unique")

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        unlabelled: list[str] = []
        for inspected in inspect_running():
            labels = inspected.get("Config", {}).get("Labels") or {}
            project = labels.get("com.docker.compose.project")
            service = labels.get("com.docker.compose.service")
            name = str(inspected.get("Name", "")).lstrip("/")
            if not project or not service:
                unlabelled.append(name)
                continue
            grouped[(str(project), str(service))].append(inspected)

        contract_by_key = {
            (item["compose_project"], item["compose_service"]): item for item in contracts
        }
        unknown_keys = sorted(set(grouped) - set(contract_by_key))
        missing_keys = sorted(set(contract_by_key) - set(grouped))
        violations: list[dict[str, Any]] = []
        for name in sorted(unlabelled):
            violations.append({"type": "running_container_without_compose_authority", "container": name})
        for project, service in unknown_keys:
            violations.append(
                {"type": "running_workload_missing_from_source_lock", "compose_project": project, "compose_service": service}
            )
        for project, service in missing_keys:
            violations.append(
                {"type": "source_locked_workload_not_running", "compose_project": project, "compose_service": service}
            )

        records: list[dict[str, Any]] = []
        for key, contract in sorted(contract_by_key.items()):
            instances = grouped.get(key, [])
            instance_records: list[dict[str, Any]] = []
            if len(instances) != contract["expected_instances"]:
                violations.append(
                    {
                        "type": "instance_count_mismatch",
                        "workload": contract["id"],
                        "observed": len(instances),
                        "expected": contract["expected_instances"],
                    }
                )
            for inspected in instances:
                config = inspected.get("Config") or {}
                labels = config.get("Labels") or {}
                observed_image = str(config.get("Image") or "")
                instance_violations: list[str] = []
                if observed_image != contract["image"]:
                    instance_violations.append("image_digest_reference_mismatch")
                if contract["source_type"] == "github":
                    if labels.get("org.opencontainers.image.source") != contract["source_reference"]:
                        instance_violations.append("oci_source_mismatch")
                    if labels.get("org.opencontainers.image.revision") != contract["revision"]:
                        instance_violations.append("oci_revision_mismatch")
                for detail in instance_violations:
                    violations.append(
                        {"type": detail, "workload": contract["id"], "container_id": inspected["Id"][:12]}
                    )
                instance_records.append(
                    {
                        "container_id": inspected["Id"][:12],
                        "container_name": str(inspected.get("Name", "")).lstrip("/"),
                        "image": observed_image,
                        "oci_source": labels.get("org.opencontainers.image.source"),
                        "oci_revision": labels.get("org.opencontainers.image.revision"),
                        "violations": instance_violations,
                    }
                )
            records.append({**contract, "instances": instance_records})

        status = "PASS" if not violations else "FAIL"
        payload = {
            "schema": "codestra.server-a-runtime-source-lock-result.v1",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_server": "65.109.65.169",
            "running_container_count": sum(len(value) for value in grouped.values()) + len(unlabelled),
            "source_locked_workload_count": len(contracts),
            "unknown_runtime_components": len(unlabelled) + len(unknown_keys),
            "missing_source_locked_workloads": len(missing_keys),
            "mismatch_count": len(violations),
            "workloads": records,
            "violations": violations,
        }
        atomic_write_json(args.evidence, payload)
        publish_metrics(args.metrics, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if status == "PASS" else 1
    except (ContractError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        failure = {
            "schema": "codestra.server-a-runtime-source-lock-result.v1",
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
        print(f"RUNTIME_SOURCE_LOCK_AUDIT=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
