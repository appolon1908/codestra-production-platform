#!/usr/bin/env python3
"""Validate production source-lock and immutable-candidate evidence fail closed.

The default mode validates that repository evidence is internally honest: incomplete
or placeholder evidence is permitted only while every deployment/canary/certification
authority remains false. ``--require-complete`` is the final release gate and fails
until all 64 workload records, all 15 business API records, and all supporting
artifact/runtime/recovery evidence are complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = ROOT / "config" / "production-certification-authority.v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
CHECKSUM_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")

SOURCE_KEYS = (
    "protected_source_sha",
    "source_sha",
    "git_sha",
    "commit_sha",
    "revision",
    "source_commit",
)
IMAGE_KEYS = (
    "oci_image_digest",
    "image_digest",
    "digest",
    "image",
    "image_reference",
)
REPOSITORY_KEYS = ("repository", "repo", "source_repository")
SIGNATURE_KEYS = ("signature_reference", "signature", "cosign_bundle", "signature_uri")
SBOM_KEYS = ("sbom_reference", "sbom", "sbom_uri")
PROVENANCE_KEYS = ("provenance_reference", "provenance", "attestation", "provenance_uri")
CONFIG_KEYS = ("configuration_checksum", "config_checksum", "configuration_sha256")
RUNTIME_SOURCE_KEYS = ("runtime_source_readback", "runtime_source_sha", "runtime_revision")
RUNTIME_DIGEST_KEYS = ("runtime_digest_readback", "runtime_image_digest", "runtime_digest")
ROLLBACK_SOURCE_KEYS = ("rollback_source_sha", "previous_source_sha", "rollback_revision")
ROLLBACK_DIGEST_KEYS = ("rollback_image_digest", "previous_image_digest", "rollback_digest")


def fail(message: str) -> None:
    print(f"PRODUCTION_CERTIFICATION_AUTHORITY_ERROR={message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot parse {path.relative_to(ROOT)}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must contain an object")
    return value


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        fail(f"cannot parse {path.relative_to(ROOT)}: {exc}")


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def pick(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return None


def normalize(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def is_placeholder(value: Any, forbidden: set[str]) -> bool:
    text = normalize(value)
    if not text:
        return True
    upper = text.upper()
    if upper in forbidden:
        return True
    if any(token in upper for token in ("REPLACE_WITH", "PLACEHOLDER", "EXAMPLE_ONLY")):
        return True
    if set(text) == {"0"}:
        return True
    return False


def candidate_lists(document: Any) -> list[tuple[str, list[dict[str, Any]]]]:
    result: list[tuple[str, list[dict[str, Any]]]] = []
    preferred = {"workloads", "components", "candidates", "services", "artifacts"}
    for path, value in walk(document):
        if not isinstance(value, list) or not value:
            continue
        records = [item for item in value if isinstance(item, dict)]
        if len(records) != len(value):
            continue
        leaf = path.rsplit(".", 1)[-1].lower()
        if leaf in preferred or any(pick(item, REPOSITORY_KEYS + SOURCE_KEYS + IMAGE_KEYS) is not None for item in records):
            result.append((path, records))
    return result


def select_records(document: Any, expected: int, preferred_leaf: str) -> tuple[str, list[dict[str, Any]]]:
    lists = candidate_lists(document)
    exact = [item for item in lists if len(item[1]) == expected]
    if exact:
        exact.sort(key=lambda item: (not item[0].lower().endswith(preferred_leaf), len(item[0])))
        return exact[0]
    if lists:
        lists.sort(key=lambda item: len(item[1]), reverse=True)
        return lists[0]
    return "$", []


def validate_workload(
    record: dict[str, Any],
    index: int,
    forbidden: set[str],
) -> list[str]:
    blockers: list[str] = []
    label = normalize(record.get("name") or record.get("workload") or record.get("service") or f"index-{index}")

    repository = pick(record, REPOSITORY_KEYS)
    if is_placeholder(repository, forbidden) or "/" not in normalize(repository):
        blockers.append(f"workload {label}: canonical repository missing")

    source = normalize(pick(record, SOURCE_KEYS))
    if not SHA_RE.fullmatch(source):
        blockers.append(f"workload {label}: protected source SHA missing or invalid")

    image = normalize(pick(record, IMAGE_KEYS))
    if not (IMAGE_RE.fullmatch(image) or DIGEST_RE.fullmatch(image)):
        blockers.append(f"workload {label}: immutable OCI digest missing or invalid")
    if ":latest" in image.lower():
        blockers.append(f"workload {label}: mutable latest tag is forbidden")

    for description, keys in (
        ("signature reference", SIGNATURE_KEYS),
        ("SBOM reference", SBOM_KEYS),
        ("provenance reference", PROVENANCE_KEYS),
    ):
        if is_placeholder(pick(record, keys), forbidden):
            blockers.append(f"workload {label}: {description} missing")

    checksum = normalize(pick(record, CONFIG_KEYS))
    if not CHECKSUM_RE.fullmatch(checksum):
        blockers.append(f"workload {label}: configuration checksum missing or invalid")

    runtime_source = normalize(pick(record, RUNTIME_SOURCE_KEYS))
    if not SHA_RE.fullmatch(runtime_source) or (source and runtime_source != source):
        blockers.append(f"workload {label}: runtime source readback does not match protected source")

    runtime_digest = normalize(pick(record, RUNTIME_DIGEST_KEYS))
    expected_digest = image.rsplit("@", 1)[-1] if "@" in image else image
    if not DIGEST_RE.fullmatch(runtime_digest) or (expected_digest and runtime_digest != expected_digest):
        blockers.append(f"workload {label}: runtime digest readback does not match candidate")

    rollback_source = normalize(pick(record, ROLLBACK_SOURCE_KEYS))
    rollback_digest = normalize(pick(record, ROLLBACK_DIGEST_KEYS))
    if not SHA_RE.fullmatch(rollback_source):
        blockers.append(f"workload {label}: rollback source SHA missing")
    if not (DIGEST_RE.fullmatch(rollback_digest) or IMAGE_RE.fullmatch(rollback_digest)):
        blockers.append(f"workload {label}: rollback digest missing")
    if source and rollback_source == source and expected_digest and rollback_digest.endswith(expected_digest):
        blockers.append(f"workload {label}: rollback candidate is identical to forward candidate")

    return blockers


def validate_api_record(record: dict[str, Any], index: int, forbidden: set[str]) -> list[str]:
    blockers: list[str] = []
    label = normalize(record.get("application") or record.get("service") or record.get("name") or f"index-{index}")
    for key in ("health", "readiness", "version", "capabilities"):
        value = record.get(key)
        if isinstance(value, dict):
            state = value.get("status") or value.get("result")
        else:
            state = value
        if normalize(state).upper() != "PASS":
            blockers.append(f"business API {label}: {key} is not PASS")
    for key in ("openapi_alignment", "gateway_alignment", "runtime_attribution"):
        state = record.get(key)
        if isinstance(state, dict):
            state = state.get("status") or state.get("result")
        if normalize(state).upper() != "PASS":
            blockers.append(f"business API {label}: {key} is not PASS")
    if is_placeholder(record.get("source_sha"), forbidden) or not SHA_RE.fullmatch(normalize(record.get("source_sha"))):
        blockers.append(f"business API {label}: source SHA missing")
    digest = normalize(record.get("image_digest"))
    if not DIGEST_RE.fullmatch(digest):
        blockers.append(f"business API {label}: image digest missing")
    return blockers


def find_status(document: Any, names: set[str]) -> list[Any]:
    result: list[Any] = []
    for path, value in walk(document):
        leaf = path.rsplit(".", 1)[-1].lower()
        if leaf in names:
            result.append(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    authority = load_json(AUTHORITY_PATH)
    if authority.get("schema_version") != 1:
        fail("authority schema_version must be 1")
    if authority.get("authority_id") != "codestra.production-certification.v1":
        fail("authority_id mismatch")

    safety = authority.get("safety_controls")
    if not isinstance(safety, dict) or not safety:
        fail("safety_controls must be a non-empty object")
    enabled_safety = sorted(key for key, value in safety.items() if value is not False)
    if enabled_safety:
        fail(f"all safety controls must remain false: {enabled_safety}")

    source_lock_path = ROOT / normalize(authority.get("source_lock_path"))
    matrix_path = ROOT / normalize(authority.get("candidate_matrix_path"))
    source_lock = load_yaml(source_lock_path)
    matrix = load_yaml(matrix_path)

    forbidden = {str(value).upper() for value in authority.get("forbidden_placeholder_values", [])}
    blockers: list[str] = []

    workload_path, workloads = select_records(
        matrix,
        int(authority.get("required_workload_count", 64)),
        "workloads",
    )
    required_workloads = int(authority.get("required_workload_count", 64))
    if len(workloads) != required_workloads:
        blockers.append(
            f"immutable candidate matrix exposes {len(workloads)} workload records at {workload_path}; expected {required_workloads}"
        )
    for index, record in enumerate(workloads):
        blockers.extend(validate_workload(record, index, forbidden))

    api_path, apis = select_records(
        source_lock,
        int(authority.get("required_business_api_count", 15)),
        "business_apis",
    )
    required_apis = int(authority.get("required_business_api_count", 15))
    if len(apis) != required_apis:
        blockers.append(
            f"source lock exposes {len(apis)} business API records at {api_path}; expected {required_apis}"
        )
    else:
        for index, record in enumerate(apis):
            blockers.extend(validate_api_record(record, index, forbidden))

    for path, value in walk({"source_lock": source_lock, "candidate_matrix": matrix}):
        if isinstance(value, str):
            upper = value.strip().upper()
            if is_placeholder(value, forbidden):
                blockers.append(f"placeholder evidence remains at {path}: {upper or '<empty>'}")
            if ":latest" in value.lower():
                blockers.append(f"mutable latest image reference remains at {path}")

    source_statuses = find_status(source_lock, {"status", "overall_status", "source_lock_status"})
    matrix_authorizations = find_status(matrix, {"deployment_authorized", "production_authorized"})
    authority_claims = {
        "deployment_authorized": authority.get("deployment_authorized"),
        "production_canary_authorized": authority.get("production_canary_authorized"),
        "production_certified": authority.get("production_certified"),
    }

    any_positive_claim = any(value is True for value in authority_claims.values())
    any_source_pass = any(normalize(value).upper() == "PASS" for value in source_statuses)
    any_matrix_authorized = any(value is True for value in matrix_authorizations)
    if blockers and (any_positive_claim or any_source_pass or any_matrix_authorized):
        fail("incomplete canonical evidence is paired with a positive release/deployment claim")

    report = {
        "schema_version": 1,
        "status": "PASS" if not blockers else "BLOCKED",
        "source_lock": str(source_lock_path.relative_to(ROOT)),
        "candidate_matrix": str(matrix_path.relative_to(ROOT)),
        "source_lock_sha256": hashlib.sha256(source_lock_path.read_bytes()).hexdigest(),
        "candidate_matrix_sha256": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
        "workload_record_path": workload_path,
        "workload_records": len(workloads),
        "required_workload_records": required_workloads,
        "business_api_record_path": api_path,
        "business_api_records": len(apis),
        "required_business_api_records": required_apis,
        "blocker_count": len(blockers),
        "blockers": sorted(set(blockers)),
        "deployment_authorized": False if blockers else bool(authority.get("deployment_authorized")),
        "production_canary_authorized": False if blockers else bool(authority.get("production_canary_authorized")),
        "production_certified": False if blockers else bool(authority.get("production_certified")),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if blockers:
        print(f"PRODUCTION_CERTIFICATION_CANONICAL_EVIDENCE=BLOCKED ({len(set(blockers))} blockers)")
        if args.require_complete:
            return 1
    else:
        print("PRODUCTION_CERTIFICATION_CANONICAL_EVIDENCE=PASS")
    print("PRODUCTION_CERTIFICATION_FAIL_CLOSED_AUTHORITY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
