#!/usr/bin/env python3
"""Validate the exact 24-workload production disposition without inventing runtime proof."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evidence/server65/UNPINNED-CUSTOM-DEPLOYMENTS.yaml"
DISPOSITION = ROOT / "evidence/server65/WORKLOAD-DISPOSITION-24-20260903.yaml"
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ALLOWED_DISPOSITIONS = {"RETIRE_FROM_PRODUCTION", "REPLACE_WITH_IMMUTABLE"}
ALLOWED_STATES = {"READY", "BLOCKED"}


def fail(message: str) -> None:
    raise ValueError(message)


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"{path.name}: root must be an object")
    return data


def validate(source: dict, document: dict) -> None:
    if source.get("count") != 24:
        fail("source inventory must contain exactly 24 records")
    source_rows = source.get("deployments")
    rows = document.get("records")
    if not isinstance(source_rows, list) or len(source_rows) != 24:
        fail("source inventory rows are incomplete")
    if not isinstance(rows, list) or len(rows) != 24:
        fail("disposition must contain exactly 24 records")

    source_by_name = {row.get("container"): row for row in source_rows}
    rows_by_name = {row.get("container"): row for row in rows}
    if len(source_by_name) != 24 or len(rows_by_name) != 24:
        fail("container names must be present and unique")
    if set(source_by_name) != set(rows_by_name):
        fail("disposition coverage differs from the captured 24-workload inventory")

    if document.get("schema_version") != "codestra.workload-disposition.v1":
        fail("unexpected disposition schema")
    if document.get("target_server") != "65.109.65.169":
        fail("unexpected production target")
    if document.get("production_changed") is not False:
        fail("repository evidence must not claim a production change")
    if document.get("runtime_contacted") is not False:
        fail("repository evidence must not claim runtime contact")

    controls = document.get("safety_controls")
    if not isinstance(controls, dict) or not controls:
        fail("safety controls are missing")
    if any(value is not False for value in controls.values()):
        fail("every live-effect safety control must remain false")

    counts: Counter[str] = Counter()
    blocked_by_authority: Counter[str] = Counter()
    for name, row in rows_by_name.items():
        original = source_by_name[name]
        if row.get("current_image") != original.get("image"):
            fail(f"{name}: current image differs from captured inventory")
        if row.get("current_image_id") != original.get("image_id"):
            fail(f"{name}: current image ID differs from captured inventory")
        if not DIGEST.fullmatch(str(row.get("current_image_id", ""))):
            fail(f"{name}: current image ID is not an exact digest")

        disposition = row.get("disposition")
        if disposition not in ALLOWED_DISPOSITIONS:
            fail(f"{name}: unsupported disposition")
        counts[disposition] += 1

        if disposition == "RETIRE_FROM_PRODUCTION":
            if not str(row.get("reason", "")).strip():
                fail(f"{name}: retirement reason is required")
            forbidden = {
                "candidate_repository",
                "candidate_source_sha",
                "candidate_image",
                "candidate_image_digest",
                "candidate_state",
                "authority",
            }
            if forbidden.intersection(row):
                fail(f"{name}: retirement record must not claim a replacement")
            continue

        state = row.get("candidate_state")
        if state not in ALLOWED_STATES:
            fail(f"{name}: replacement state must be READY or BLOCKED")
        for key in ("authority", "candidate_repository", "candidate_source_sha", "candidate_image", "candidate_image_digest"):
            if not str(row.get(key, "")).strip():
                fail(f"{name}: missing {key}")
        if state == "READY":
            if not SHA.fullmatch(str(row["candidate_source_sha"])):
                fail(f"{name}: ready candidate source is not an exact SHA")
            if not DIGEST.fullmatch(str(row["candidate_image_digest"])):
                fail(f"{name}: ready candidate image is not an exact digest")
            if ":latest" in str(row["candidate_image"]) or "@" in str(row["candidate_image"]):
                fail(f"{name}: candidate image repository must be untagged and digest-free")
        else:
            if not str(row["candidate_source_sha"]).startswith("PENDING_"):
                fail(f"{name}: blocked source must be explicitly pending")
            if not str(row["candidate_image_digest"]).startswith("PENDING_"):
                fail(f"{name}: blocked image digest must be explicitly pending")
            blocked_by_authority[str(row["authority"])] += 1

    ready_count = sum(
        row.get("disposition") == "REPLACE_WITH_IMMUTABLE" and row.get("candidate_state") == "READY"
        for row in rows
    )
    blocked_count = sum(
        row.get("disposition") == "REPLACE_WITH_IMMUTABLE" and row.get("candidate_state") == "BLOCKED"
        for row in rows
    )
    if counts["RETIRE_FROM_PRODUCTION"] != 12:
        fail("exactly 12 production contaminants must be retired")
    if counts["REPLACE_WITH_IMMUTABLE"] != 12:
        fail("exactly 12 production workloads require immutable replacements")
    if ready_count + blocked_count != 12:
        fail("replacement accounting is inconsistent")

    authorities = document.get("blocking_authorities")
    if not isinstance(authorities, list):
        fail("blocking authority list is missing")
    declared = {str(row.get("id")): row for row in authorities}
    if set(declared) != set(blocked_by_authority):
        fail("blocked records and blocking authority list differ")
    for authority, count in blocked_by_authority.items():
        if declared[authority].get("records") != count:
            fail(f"{authority}: blocked record count differs")
        if not str(declared[authority].get("reason", "")).strip():
            fail(f"{authority}: blocker reason is required")

    summary = document.get("summary", {})
    expected_summary = {
        "records_total": 24,
        "retire_from_production": 12,
        "immutable_replacements_ready": ready_count,
        "immutable_replacements_pending": blocked_count,
        "blocking_authorities": len(blocked_by_authority),
        "unresolved_unknown_records": 0,
    }
    if summary != expected_summary:
        fail(f"summary differs from records: expected {expected_summary!r}")

    expected_status = "PASS" if not blocked_by_authority else "BLOCKED"
    if document.get("status") != expected_status:
        fail(f"status must be {expected_status}")
    if expected_status == "PASS" and (
        counts["RETIRE_FROM_PRODUCTION"] != 12 or ready_count != 12
    ):
        fail("PASS requires 12 completed retirements and 12 ready replacements")


def main() -> int:
    try:
        validate(load(SOURCE), load(DISPOSITION))
    except (OSError, yaml.YAMLError, ValueError) as error:
        print(f"WORKLOAD_DISPOSITION_24=FAIL: {error}", file=sys.stderr)
        return 1
    print("WORKLOAD_DISPOSITION_24=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
