#!/usr/bin/env python3
"""Validate isolated staging, workload/API, recovery, canary and soak evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "config" / "production-runtime-certification.template.v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")
PASS = "PASS"


def fail(message: str) -> None:
    print(f"PRODUCTION_RUNTIME_CERTIFICATION_ERROR={message}", file=sys.stderr)
    raise SystemExit(1)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot parse {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path} must contain an object")
    return value


def state(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status") or value.get("result")
    return str(value or "").strip().upper()


def require_pass(value: Any, label: str, blockers: list[str]) -> None:
    if state(value) != PASS:
        blockers.append(f"{label} is not PASS")


def require_zero(value: Any, label: str, blockers: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        blockers.append(f"{label} must equal 0")


def require_nonnegative(value: Any, label: str, blockers: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        blockers.append(f"{label} must be a non-negative integer")


def require_sha(value: Any, label: str, blockers: list[str]) -> None:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        blockers.append(f"{label} must be a full protected Git SHA")


def require_digest(value: Any, label: str, blockers: list[str]) -> None:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        blockers.append(f"{label} must be an immutable sha256 digest")


def require_checksum(value: Any, label: str, blockers: list[str]) -> None:
    if not isinstance(value, str) or not CHECKSUM_RE.fullmatch(value):
        blockers.append(f"{label} must be a 64-character SHA-256 checksum")


def validate_template(document: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if document.get("schema_version") != 1:
        blockers.append("schema_version must equal 1")
    if document.get("template") is not True:
        blockers.append("repository template must retain template=true")
    if document.get("production_certified") is not False:
        blockers.append("repository template cannot claim production certification")
    safety = document.get("safety")
    if not isinstance(safety, dict) or not safety:
        blockers.append("safety map is missing")
    else:
        enabled = sorted(name for name, value in safety.items() if value is not False)
        if enabled:
            blockers.append(f"template safety controls must all be false: {enabled}")
    canary = document.get("production_canary")
    if not isinstance(canary, dict):
        blockers.append("production_canary object is missing")
    else:
        if canary.get("traffic_percent") != 0:
            blockers.append("template canary traffic must be 0")
        if canary.get("allowed_methods") != ["GET", "HEAD"]:
            blockers.append("canary methods must be exactly GET and HEAD")
    if document.get("workloads") != []:
        blockers.append("template workload list must be empty")
    if document.get("business_apis") != []:
        blockers.append("template business API list must be empty")
    gateway = document.get("gateway")
    if not isinstance(gateway, dict) or gateway.get("expected_route_count") != 29:
        blockers.append("gateway expected route count must be 29")
    return blockers


def validate_workload(item: Any, index: int) -> list[str]:
    blockers: list[str] = []
    if not isinstance(item, dict):
        return [f"workload[{index}] must be an object"]
    name = str(item.get("name") or item.get("workload") or f"index-{index}")
    repository = item.get("repository")
    if not isinstance(repository, str) or "/" not in repository:
        blockers.append(f"workload {name}: repository is missing")
    require_sha(item.get("source_sha"), f"workload {name}: source_sha", blockers)
    require_digest(item.get("image_digest"), f"workload {name}: image_digest", blockers)
    require_sha(item.get("runtime_source_sha"), f"workload {name}: runtime_source_sha", blockers)
    require_digest(item.get("runtime_image_digest"), f"workload {name}: runtime_image_digest", blockers)
    if item.get("runtime_source_sha") != item.get("source_sha"):
        blockers.append(f"workload {name}: runtime source differs from certified source")
    if item.get("runtime_image_digest") != item.get("image_digest"):
        blockers.append(f"workload {name}: runtime digest differs from certified digest")
    require_checksum(item.get("configuration_checksum"), f"workload {name}: configuration_checksum", blockers)
    for key in ("signature", "sbom", "provenance", "vulnerability_gate", "health", "readiness", "identity"):
        require_pass(item.get(key), f"workload {name}: {key}", blockers)
    require_zero(item.get("restart_count"), f"workload {name}: restart_count", blockers)
    require_zero(item.get("source_runtime_drift"), f"workload {name}: source_runtime_drift", blockers)
    if item.get("prometheus_target_required") is True:
        require_pass(item.get("prometheus_target"), f"workload {name}: prometheus_target", blockers)
    rollback = item.get("rollback")
    if not isinstance(rollback, dict):
        blockers.append(f"workload {name}: rollback object is missing")
    else:
        require_sha(rollback.get("source_sha"), f"workload {name}: rollback source_sha", blockers)
        require_digest(rollback.get("image_digest"), f"workload {name}: rollback image_digest", blockers)
        if rollback.get("source_sha") == item.get("source_sha") and rollback.get("image_digest") == item.get("image_digest"):
            blockers.append(f"workload {name}: rollback equals forward candidate")
    return blockers


def validate_api(item: Any, index: int) -> list[str]:
    blockers: list[str] = []
    if not isinstance(item, dict):
        return [f"business_apis[{index}] must be an object"]
    name = str(item.get("application") or item.get("name") or f"index-{index}")
    require_sha(item.get("source_sha"), f"business API {name}: source_sha", blockers)
    require_digest(item.get("image_digest"), f"business API {name}: image_digest", blockers)
    for key in (
        "health",
        "readiness",
        "version",
        "capabilities",
        "openapi_source_runtime_alignment",
        "gateway_application_alignment",
        "runtime_attribution",
        "authentication_required",
        "wrong_role_denied",
        "wrong_business_denied",
        "write_methods_denied",
        "tls_verified",
    ):
        require_pass(item.get(key), f"business API {name}: {key}", blockers)
    require_zero(item.get("unexpected_404"), f"business API {name}: unexpected_404", blockers)
    require_zero(item.get("unexpected_5xx"), f"business API {name}: unexpected_5xx", blockers)
    return blockers


def validate_route(item: Any, index: int) -> list[str]:
    blockers: list[str] = []
    if not isinstance(item, dict):
        return [f"gateway.routes[{index}] must be an object"]
    name = str(item.get("name") or item.get("route") or f"index-{index}")
    require_pass(item.get("status"), f"gateway route {name}: status", blockers)
    method = item.get("method")
    if method not in {"GET", "HEAD"}:
        blockers.append(f"gateway route {name}: certification method must be GET or HEAD")
    code = item.get("http_status")
    if isinstance(code, bool) or not isinstance(code, int) or code < 100 or code > 599:
        blockers.append(f"gateway route {name}: http_status is invalid")
    elif code == 404 or code >= 500:
        blockers.append(f"gateway route {name}: 404/5xx cannot certify the route")
    require_sha(item.get("source_sha"), f"gateway route {name}: source_sha", blockers)
    return blockers


def validate_complete(document: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if document.get("schema_version") != 1:
        blockers.append("schema_version must equal 1")
    if document.get("template") is not False:
        blockers.append("executed evidence must set template=false")
    if not isinstance(document.get("candidate_id"), str) or not document.get("candidate_id"):
        blockers.append("candidate_id is missing")
    require_checksum(document.get("source_lock_sha256"), "source_lock_sha256", blockers)
    require_checksum(document.get("candidate_matrix_sha256"), "candidate_matrix_sha256", blockers)

    host = document.get("staging_host")
    if not isinstance(host, dict):
        blockers.append("staging_host evidence is missing")
    else:
        require_pass(host.get("status"), "staging_host status", blockers)
        require_sha(host.get("workflow_source_sha"), "staging_host workflow_source_sha", blockers)
        require_checksum(host.get("configuration_checksum"), "staging_host configuration_checksum", blockers)
        for key in ("workflow_run_id", "provider_resource_id", "private_ip", "ssh_host_key_fingerprint"):
            if not isinstance(host.get(key), (str, int)) or str(host.get(key)).strip() == "":
                blockers.append(f"staging_host {key} is missing")

    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        blockers.append("artifact summary is missing")
    else:
        require_pass(artifacts.get("status"), "artifacts status", blockers)
        for key in ("all_exact_digest", "all_signed", "all_sbom_verified", "all_provenance_verified", "all_vulnerability_gates_pass"):
            if artifacts.get(key) is not True:
                blockers.append(f"artifacts {key} must be true")

    workloads = document.get("workloads")
    if not isinstance(workloads, list) or len(workloads) != 64:
        blockers.append(f"exactly 64 workload records are required; found {len(workloads) if isinstance(workloads, list) else 0}")
    else:
        for index, item in enumerate(workloads):
            blockers.extend(validate_workload(item, index))
        names = [str(item.get("name") or item.get("workload")) for item in workloads if isinstance(item, dict)]
        if len(names) != len(set(names)):
            blockers.append("workload names must be unique")

    apis = document.get("business_apis")
    if not isinstance(apis, list) or len(apis) != 15:
        blockers.append(f"exactly 15 business API records are required; found {len(apis) if isinstance(apis, list) else 0}")
    else:
        for index, item in enumerate(apis):
            blockers.extend(validate_api(item, index))
        names = [str(item.get("application") or item.get("name")) for item in apis if isinstance(item, dict)]
        if len(names) != len(set(names)):
            blockers.append("business API names must be unique")

    gateway = document.get("gateway")
    if not isinstance(gateway, dict):
        blockers.append("gateway evidence is missing")
    else:
        routes = gateway.get("routes")
        if gateway.get("expected_route_count") != 29:
            blockers.append("gateway expected_route_count must equal 29")
        if not isinstance(routes, list) or len(routes) != 29:
            blockers.append(f"exactly 29 gateway route records are required; found {len(routes) if isinstance(routes, list) else 0}")
        else:
            for index, item in enumerate(routes):
                blockers.extend(validate_route(item, index))

    staging = document.get("staging")
    if not isinstance(staging, dict):
        blockers.append("staging evidence is missing")
    else:
        require_pass(staging.get("status"), "staging status", blockers)
        if staging.get("candidate_unchanged") is not True:
            blockers.append("staging candidate must be unchanged")
        require_pass(staging.get("cross_business_denial"), "staging cross_business_denial", blockers)
        for key in ("secrets_in_logs", "high_cardinality_sensitive_labels", "unhealthy_containers", "restarting_containers", "down_prometheus_targets", "actionable_alerts", "failed_systemd_units"):
            require_zero(staging.get(key), f"staging {key}", blockers)

    recovery = document.get("backup_restore")
    if not isinstance(recovery, dict):
        blockers.append("backup_restore evidence is missing")
    else:
        for key in ("status", "database_backup", "off_host_copy", "odoo_filestore_backup", "configuration_backup", "openbao_snapshot", "isolated_restore", "data_integrity"):
            require_pass(recovery.get(key), f"backup_restore {key}", blockers)
        require_nonnegative(recovery.get("rto_seconds"), "backup_restore rto_seconds", blockers)
        require_nonnegative(recovery.get("rpo_seconds"), "backup_restore rpo_seconds", blockers)
        require_zero(recovery.get("residual_resources"), "backup_restore residual_resources", blockers)

    rollback = document.get("rollback")
    if not isinstance(rollback, dict):
        blockers.append("rollback evidence is missing")
    else:
        require_pass(rollback.get("status"), "rollback status", blockers)
        if not isinstance(rollback.get("previous_candidate_id"), str) or not rollback.get("previous_candidate_id"):
            blockers.append("rollback previous_candidate_id is missing")
        if rollback.get("previous_candidate_id") == document.get("candidate_id"):
            blockers.append("rollback candidate cannot equal forward candidate")
        if rollback.get("source_and_digest_verified") is not True:
            blockers.append("rollback source_and_digest_verified must be true")
        for key in ("health_readback", "readiness_readback", "version_readback", "data_integrity"):
            require_pass(rollback.get(key), f"rollback {key}", blockers)
        require_nonnegative(rollback.get("rto_seconds"), "rollback rto_seconds", blockers)

    canary = document.get("production_canary")
    if not isinstance(canary, dict):
        blockers.append("production_canary evidence is missing")
    else:
        require_pass(canary.get("status"), "production_canary status", blockers)
        percent = canary.get("traffic_percent")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not (0 < percent <= 1):
            blockers.append("production canary traffic must be greater than 0 and no more than 1 percent")
        if canary.get("allowed_methods") != ["GET", "HEAD"]:
            blockers.append("production canary methods must be exactly GET and HEAD")
        for key in ("observed_write_requests", "source_mismatch", "digest_mismatch", "unexpected_404", "unexpected_5xx", "cross_business_leaks", "call_delta", "email_delta", "sms_delta", "provider_effect_delta"):
            require_zero(canary.get(key), f"production_canary {key}", blockers)
        if canary.get("automatic_rollback_ready") is not True:
            blockers.append("production canary automatic rollback must be ready")

    soak = document.get("soak")
    if not isinstance(soak, dict):
        blockers.append("soak evidence is missing")
    else:
        require_pass(soak.get("status"), "soak status", blockers)
        duration = soak.get("duration_seconds")
        minimum = soak.get("minimum_duration_seconds")
        require_nonnegative(duration, "soak duration_seconds", blockers)
        require_nonnegative(minimum, "soak minimum_duration_seconds", blockers)
        if isinstance(duration, int) and isinstance(minimum, int) and duration < minimum:
            blockers.append("soak duration is below the required minimum")
        for key in ("unhealthy_containers", "restarting_containers", "down_prometheus_targets", "actionable_alerts", "failed_systemd_units", "source_runtime_drift"):
            require_zero(soak.get(key), f"soak {key}", blockers)
        if soak.get("disk_headroom_pass") is not True:
            blockers.append("soak disk_headroom_pass must be true")
        if soak.get("wal_backlog_bounded") is not True:
            blockers.append("soak wal_backlog_bounded must be true")

    safety = document.get("safety")
    if not isinstance(safety, dict) or not safety:
        blockers.append("safety evidence is missing")
    else:
        enabled = sorted(name for name, value in safety.items() if value is not False)
        if enabled:
            blockers.append(f"forbidden production effects or bypasses are enabled: {enabled}")

    if blockers and document.get("production_certified") is True:
        blockers.append("production_certified cannot be true while mandatory gates fail")
    if not blockers and document.get("production_certified") is not True:
        blockers.append("production_certified must be true only after every mandatory gate passes")
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=TEMPLATE)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    document = load(args.evidence)
    blockers = validate_complete(document) if args.require_complete else validate_template(document)
    unique = sorted(set(blockers))
    report = {
        "schema_version": 1,
        "evidence": str(args.evidence),
        "evidence_sha256": hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
        "mode": "complete" if args.require_complete else "template",
        "status": "PASS" if not unique else "BLOCKED",
        "blocker_count": len(unique),
        "blockers": unique,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if unique:
        print(f"PRODUCTION_RUNTIME_CERTIFICATION=BLOCKED ({len(unique)} blockers)")
        return 1
    print("PRODUCTION_RUNTIME_CERTIFICATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
