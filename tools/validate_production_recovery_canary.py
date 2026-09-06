#!/usr/bin/env python3
"""Validate paired recovery, rollback, read-only canary, and soak evidence.

The validator is intentionally non-operational: it reads sanitized evidence only and
cannot initiate a backup, restore, deployment, canary, rollback, or runtime change.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "production-recovery-canary-policy.v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
FORBIDDEN_TEXT = (
    "UNKNOWN", "PENDING", "NOT_RUN", "NOT_STARTED", "NONE", "TBD", "TODO",
    "REPLACE_ME", "UNVERIFIED", "UNRESOLVED", "LOCAL_ONLY"
)
SECRET_KEY_FRAGMENTS = (
    "password", "private_key", "secret_value", "access_token", "refresh_token",
    "authorization", "cookie_value", "recovery_share", "unseal_key", "root_token"
)


class EvidenceError(RuntimeError):
    """Malformed evidence or policy input."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot parse JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON root must be an object: {path}")
    return value


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def parse_time(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise EvidenceError(f"{path} must be an RFC3339 timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EvidenceError(f"{path} is not a valid RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def require_pass(value: Any, path: str) -> None:
    if value != "PASS":
        raise EvidenceError(f"{path} must be PASS")


def require_nonnegative_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceError(f"{path} must be a non-negative integer")
    return value


def require_positive_int(value: Any, path: str) -> int:
    value = require_nonnegative_int(value, path)
    if value == 0:
        raise EvidenceError(f"{path} must be positive")
    return value


def require_reference(value: Any, path: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < 8:
        raise EvidenceError(f"{path} must contain an evidence reference")
    upper = value.upper()
    if any(marker in upper for marker in FORBIDDEN_TEXT):
        raise EvidenceError(f"{path} is unresolved")
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
        raise EvidenceError(f"{path} must not embed credentials")
    return value


def reject_secrets_and_placeholders(evidence: Any) -> None:
    for path, value in walk(evidence):
        if isinstance(value, str):
            upper = value.upper()
            if any(marker in upper for marker in FORBIDDEN_TEXT):
                raise EvidenceError(f"unresolved value at {path}")
            if "-----BEGIN" in value or upper.startswith("BEARER "):
                raise EvidenceError(f"credential-shaped value at {path}")
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower().replace("-", "_")
                if any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS):
                    if child not in (None, False, "") and not normalized.endswith("_ref"):
                        raise EvidenceError(f"secret value field is prohibited at {path}.{key}")


def validate_identity(evidence: dict[str, Any]) -> None:
    if evidence.get("schema_version") != 1:
        raise EvidenceError("schema_version must be 1")
    candidate = evidence.get("candidate")
    if not isinstance(candidate, dict):
        raise EvidenceError("candidate must be an object")
    required = {"release_id", "platform_source_sha", "endpoint_manifest_sha256"}
    if set(candidate) != required:
        raise EvidenceError("candidate fields are incomplete or unexpected")
    release_id = candidate.get("release_id")
    if not isinstance(release_id, str) or not ID_RE.fullmatch(release_id):
        raise EvidenceError("candidate.release_id is invalid")
    source_sha = candidate.get("platform_source_sha")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        raise EvidenceError("candidate.platform_source_sha is invalid")
    manifest_hash = candidate.get("endpoint_manifest_sha256")
    if not isinstance(manifest_hash, str) or not HEX64_RE.fullmatch(manifest_hash):
        raise EvidenceError("candidate.endpoint_manifest_sha256 is invalid")


def validate_recovery_entry(entry: Any, authority: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise EvidenceError(f"recovery[{authority}] must be an object")
    required = {"authority", "source_sha", "image_digest", "backup", "restore", "rollback"}
    if set(entry) != required:
        raise EvidenceError(f"recovery[{authority}] fields are incomplete or unexpected")
    if entry.get("authority") != authority:
        raise EvidenceError(f"recovery[{authority}].authority mismatch")
    source_sha = entry.get("source_sha")
    digest = entry.get("image_digest")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        raise EvidenceError(f"recovery[{authority}].source_sha is invalid")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise EvidenceError(f"recovery[{authority}].image_digest is invalid")

    backup = entry.get("backup")
    if not isinstance(backup, dict):
        raise EvidenceError(f"recovery[{authority}].backup must be an object")
    backup_required = {
        "status", "generation", "started_at", "completed_at", "artifact_sha256",
        "encrypted", "checksum_verified", "source_identity_recorded",
        "image_identity_recorded", "off_host", "evidence_ref"
    }
    if set(backup) != backup_required:
        raise EvidenceError(f"recovery[{authority}].backup fields are incomplete or unexpected")
    require_pass(backup.get("status"), f"recovery[{authority}].backup.status")
    require_reference(backup.get("generation"), f"recovery[{authority}].backup.generation")
    backup_start = parse_time(backup.get("started_at"), f"recovery[{authority}].backup.started_at")
    backup_end = parse_time(backup.get("completed_at"), f"recovery[{authority}].backup.completed_at")
    if backup_end <= backup_start:
        raise EvidenceError(f"recovery[{authority}].backup must complete after it starts")
    artifact_hash = backup.get("artifact_sha256")
    if not isinstance(artifact_hash, str) or not HEX64_RE.fullmatch(artifact_hash):
        raise EvidenceError(f"recovery[{authority}].backup.artifact_sha256 is invalid")
    for name in ("encrypted", "checksum_verified", "source_identity_recorded", "image_identity_recorded"):
        if backup.get(name) is not True:
            raise EvidenceError(f"recovery[{authority}].backup.{name} must be true")
    require_reference(backup.get("evidence_ref"), f"recovery[{authority}].backup.evidence_ref")
    off_host = backup.get("off_host")
    if not isinstance(off_host, dict) or set(off_host) != {"status", "uri_ref", "sha256"}:
        raise EvidenceError(f"recovery[{authority}].backup.off_host is invalid")
    require_pass(off_host.get("status"), f"recovery[{authority}].backup.off_host.status")
    uri_ref = require_reference(off_host.get("uri_ref"), f"recovery[{authority}].backup.off_host.uri_ref")
    if not (uri_ref.startswith("env:") or uri_ref.startswith("evidence:")):
        raise EvidenceError(f"recovery[{authority}].backup.off_host.uri_ref must be an indirect reference")
    off_host_hash = off_host.get("sha256")
    if not isinstance(off_host_hash, str) or not HEX64_RE.fullmatch(off_host_hash):
        raise EvidenceError(f"recovery[{authority}].backup.off_host.sha256 is invalid")
    if off_host_hash != artifact_hash:
        raise EvidenceError(f"recovery[{authority}] off-host checksum does not match the backup artifact")

    restore = entry.get("restore")
    if not isinstance(restore, dict):
        raise EvidenceError(f"recovery[{authority}].restore must be an object")
    restore_required = {
        "status", "isolated", "generation", "started_at", "completed_at", "rto_seconds",
        "rto_limit_seconds", "rpo_seconds", "rpo_limit_seconds", "integrity",
        "residual_resources", "health_readback", "readiness_readback", "version_readback",
        "evidence_ref"
    }
    if set(restore) != restore_required:
        raise EvidenceError(f"recovery[{authority}].restore fields are incomplete or unexpected")
    require_pass(restore.get("status"), f"recovery[{authority}].restore.status")
    if restore.get("isolated") is not True:
        raise EvidenceError(f"recovery[{authority}].restore.isolated must be true")
    if restore.get("generation") != backup.get("generation"):
        raise EvidenceError(f"recovery[{authority}] restore generation does not match backup")
    restore_start = parse_time(restore.get("started_at"), f"recovery[{authority}].restore.started_at")
    restore_end = parse_time(restore.get("completed_at"), f"recovery[{authority}].restore.completed_at")
    if restore_end <= restore_start:
        raise EvidenceError(f"recovery[{authority}].restore must complete after it starts")
    rto = require_nonnegative_int(restore.get("rto_seconds"), f"recovery[{authority}].restore.rto_seconds")
    rto_limit = require_positive_int(restore.get("rto_limit_seconds"), f"recovery[{authority}].restore.rto_limit_seconds")
    rpo = require_nonnegative_int(restore.get("rpo_seconds"), f"recovery[{authority}].restore.rpo_seconds")
    rpo_limit = require_positive_int(restore.get("rpo_limit_seconds"), f"recovery[{authority}].restore.rpo_limit_seconds")
    if rto > rto_limit:
        raise EvidenceError(f"recovery[{authority}] RTO exceeds its limit")
    if rpo > rpo_limit:
        raise EvidenceError(f"recovery[{authority}] RPO exceeds its limit")
    for name in ("integrity", "health_readback", "readiness_readback", "version_readback"):
        require_pass(restore.get(name), f"recovery[{authority}].restore.{name}")
    if restore.get("residual_resources") != 0:
        raise EvidenceError(f"recovery[{authority}].restore.residual_resources must be zero")
    require_reference(restore.get("evidence_ref"), f"recovery[{authority}].restore.evidence_ref")

    rollback = entry.get("rollback")
    if not isinstance(rollback, dict):
        raise EvidenceError(f"recovery[{authority}].rollback must be an object")
    rollback_required = {
        "status", "rehearsed", "candidate_digest", "previous_digest", "started_at",
        "completed_at", "duration_seconds", "duration_limit_seconds", "data_integrity",
        "source_readback", "digest_readback", "monitoring_continuity", "evidence_ref"
    }
    if set(rollback) != rollback_required:
        raise EvidenceError(f"recovery[{authority}].rollback fields are incomplete or unexpected")
    require_pass(rollback.get("status"), f"recovery[{authority}].rollback.status")
    if rollback.get("rehearsed") is not True:
        raise EvidenceError(f"recovery[{authority}].rollback.rehearsed must be true")
    candidate_digest = rollback.get("candidate_digest")
    previous_digest = rollback.get("previous_digest")
    if candidate_digest != digest:
        raise EvidenceError(f"recovery[{authority}] rollback candidate digest does not match runtime candidate")
    if not isinstance(previous_digest, str) or not DIGEST_RE.fullmatch(previous_digest):
        raise EvidenceError(f"recovery[{authority}].rollback.previous_digest is invalid")
    if previous_digest == candidate_digest:
        raise EvidenceError(f"recovery[{authority}] rollback candidate is a no-op")
    rollback_start = parse_time(rollback.get("started_at"), f"recovery[{authority}].rollback.started_at")
    rollback_end = parse_time(rollback.get("completed_at"), f"recovery[{authority}].rollback.completed_at")
    if rollback_end <= rollback_start:
        raise EvidenceError(f"recovery[{authority}].rollback must complete after it starts")
    duration = require_nonnegative_int(rollback.get("duration_seconds"), f"recovery[{authority}].rollback.duration_seconds")
    duration_limit = require_positive_int(rollback.get("duration_limit_seconds"), f"recovery[{authority}].rollback.duration_limit_seconds")
    if duration > duration_limit:
        raise EvidenceError(f"recovery[{authority}] rollback duration exceeds its limit")
    for name in ("data_integrity", "source_readback", "digest_readback", "monitoring_continuity"):
        require_pass(rollback.get(name), f"recovery[{authority}].rollback.{name}")
    require_reference(rollback.get("evidence_ref"), f"recovery[{authority}].rollback.evidence_ref")

    return {
        "authority": authority,
        "source_sha": source_sha,
        "image_digest": digest,
        "backup_generation": backup["generation"],
        "backup_sha256": artifact_hash,
        "rto_seconds": rto,
        "rpo_seconds": rpo,
        "rollback_previous_digest": previous_digest,
        "rollback_duration_seconds": duration,
    }


def validate_canary(value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError("canary must be an object")
    required = {
        "status", "started_at", "completed_at", "traffic_percent", "methods_observed",
        "source_match", "digest_match", "unexpected_404", "unexpected_5xx",
        "calls_delta", "emails_delta", "sms_delta", "provider_effects_delta",
        "business_writes_delta", "cross_business_leaks", "secrets_in_logs",
        "monitoring_continuity", "automatic_rollback_ready", "evidence_ref"
    }
    if set(value) != required:
        raise EvidenceError("canary fields are incomplete or unexpected")
    require_pass(value.get("status"), "canary.status")
    start = parse_time(value.get("started_at"), "canary.started_at")
    end = parse_time(value.get("completed_at"), "canary.completed_at")
    if end <= start:
        raise EvidenceError("canary must complete after it starts")
    traffic = value.get("traffic_percent")
    if isinstance(traffic, bool) or not isinstance(traffic, (int, float)) or traffic <= 0:
        raise EvidenceError("canary.traffic_percent must be positive")
    if traffic > policy["canary"]["maximum_traffic_percent"]:
        raise EvidenceError("canary traffic exceeds the one-percent limit")
    methods = value.get("methods_observed")
    allowed = set(policy["canary"]["allowed_methods"])
    if not isinstance(methods, list) or not methods or set(methods) - allowed:
        raise EvidenceError("canary methods must be a non-empty GET/HEAD subset")
    if value.get("source_match") is not True or value.get("digest_match") is not True:
        raise EvidenceError("canary source and digest must match the certified candidate")
    for name in (
        "unexpected_404", "unexpected_5xx", "calls_delta", "emails_delta", "sms_delta",
        "provider_effects_delta", "business_writes_delta", "cross_business_leaks",
        "secrets_in_logs"
    ):
        observed = require_nonnegative_int(value.get(name), f"canary.{name}")
        if observed != 0:
            raise EvidenceError(f"canary.{name} must be zero")
    require_pass(value.get("monitoring_continuity"), "canary.monitoring_continuity")
    if value.get("automatic_rollback_ready") is not True:
        raise EvidenceError("canary automatic rollback must be ready")
    require_reference(value.get("evidence_ref"), "canary.evidence_ref")
    return {
        "traffic_percent": traffic,
        "duration_seconds": int((end - start).total_seconds()),
        "methods_observed": sorted(set(methods)),
    }


def validate_soak(value: Any, policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError("soak must be an object")
    required = {
        "status", "started_at", "completed_at", "unhealthy_containers",
        "restarting_containers", "down_prometheus_targets", "actionable_alerts",
        "failed_systemd_units", "source_runtime_drift", "cross_business_leaks",
        "secrets_in_logs", "evidence_ref"
    }
    if set(value) != required:
        raise EvidenceError("soak fields are incomplete or unexpected")
    require_pass(value.get("status"), "soak.status")
    start = parse_time(value.get("started_at"), "soak.started_at")
    end = parse_time(value.get("completed_at"), "soak.completed_at")
    duration = int((end - start).total_seconds())
    if duration < policy["soak"]["minimum_duration_seconds"]:
        raise EvidenceError("soak duration is below the policy minimum")
    mapping = {
        "unhealthy_containers": "maximum_unhealthy_containers",
        "restarting_containers": "maximum_restarting_containers",
        "down_prometheus_targets": "maximum_down_prometheus_targets",
        "actionable_alerts": "maximum_actionable_alerts",
        "failed_systemd_units": "maximum_failed_systemd_units",
        "source_runtime_drift": "maximum_source_runtime_drift",
        "cross_business_leaks": "maximum_cross_business_leaks",
        "secrets_in_logs": "maximum_secrets_in_logs",
    }
    for name, policy_name in mapping.items():
        observed = require_nonnegative_int(value.get(name), f"soak.{name}")
        if observed > policy["soak"][policy_name]:
            raise EvidenceError(f"soak.{name} exceeds policy")
    require_reference(value.get("evidence_ref"), "soak.evidence_ref")
    return {"duration_seconds": duration}


def validate(evidence: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    reject_secrets_and_placeholders(evidence)
    validate_identity(evidence)
    required_root = {"schema_version", "candidate", "recovery", "canary", "soak", "safety"}
    if set(evidence) != required_root:
        raise EvidenceError("evidence root fields are incomplete or unexpected")

    required_authorities = policy.get("required_recovery_authorities")
    recovery = evidence.get("recovery")
    if not isinstance(required_authorities, list) or not required_authorities:
        raise EvidenceError("policy required_recovery_authorities is invalid")
    if not isinstance(recovery, list) or len(recovery) != len(required_authorities):
        raise EvidenceError("recovery evidence count does not match policy")
    by_authority: dict[str, Any] = {}
    for entry in recovery:
        if not isinstance(entry, dict) or not isinstance(entry.get("authority"), str):
            raise EvidenceError("each recovery entry must have an authority")
        authority = entry["authority"]
        if authority in by_authority:
            raise EvidenceError(f"duplicate recovery authority: {authority}")
        by_authority[authority] = entry
    if set(by_authority) != set(required_authorities):
        missing = sorted(set(required_authorities) - set(by_authority))
        extra = sorted(set(by_authority) - set(required_authorities))
        raise EvidenceError(f"recovery authority mismatch; missing={missing}, extra={extra}")

    recovery_summary = [
        validate_recovery_entry(by_authority[authority], authority)
        for authority in required_authorities
    ]
    canary_summary = validate_canary(evidence.get("canary"), policy)
    soak_summary = validate_soak(evidence.get("soak"), policy)

    safety = evidence.get("safety")
    required_safety = {
        "business_writes", "communications_delivery", "provider_effects",
        "financial_or_trading_mutation"
    }
    if not isinstance(safety, dict) or set(safety) != required_safety:
        raise EvidenceError("safety evidence is incomplete")
    enabled = sorted(name for name, state in safety.items() if state is not False)
    if enabled:
        raise EvidenceError(f"safety effects must remain false: {enabled}")

    return {
        "schema_version": 1,
        "status": "PASS",
        "candidate": evidence["candidate"],
        "recovery_authorities": recovery_summary,
        "canary": canary_summary,
        "soak": soak_summary,
        "safety": safety,
        "secret_values_recorded": False,
        "runtime_contacted_by_validator": False,
        "production_changed_by_validator": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--result-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate(load_json(args.evidence), load_json(args.policy))
    except EvidenceError as exc:
        print(f"PRODUCTION_RECOVERY_CANARY=BLOCKED", file=sys.stderr)
        print(f"BLOCKER={exc}", file=sys.stderr)
        return 2
    if args.result_output:
        args.result_output.parent.mkdir(parents=True, exist_ok=True)
        args.result_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PRODUCTION_RECOVERY_CANARY=PASS")
    print(f"RECOVERY_AUTHORITIES={len(result['recovery_authorities'])}")
    print(f"CANARY_PERCENT={result['canary']['traffic_percent']}")
    print(f"SOAK_SECONDS={result['soak']['duration_seconds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
