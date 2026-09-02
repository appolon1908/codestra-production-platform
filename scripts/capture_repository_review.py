#!/usr/bin/env python3
"""Capture repository evidence with canonical-name and permanent-blocker guards."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "capture_repository_review_core.py"

OPERATIONAL_BLOCKERS = (
    (
        "Codestra-SRL/codestra-middleware",
        "Canonical Middleware exact-head and protected-main workflows cannot "
        "start because the organization Actions budget is zero with "
        "prevent_further_usage enabled.",
        "evidence/repository-review/"
        "CANONICAL-MIDDLEWARE-ACTIONS-BLOCKER-20260902.md",
    ),
    (
        "Server 65 Kong runtime read-back",
        "The reviewed narrow kong-readback operator action is not installed; "
        "Infrastructure/security-owner approval is required without changing "
        "SSH or granting an arbitrary shell.",
        "evidence/server65/KONG-RUNTIME-READBACK-BLOCKER-20260902.md",
    ),
)


def load_core() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "repository_review_capture_core",
        CORE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("repository review capture core cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = load_core()

# Preserve the established public helper API for tests and callers. Functions
# that require additional policy are overridden below.
for _name, _value in vars(CORE).items():
    if not _name.startswith("_"):
        globals().setdefault(_name, _value)


def canonical_name_mismatch_record(
    repo: str,
    metadata: dict[str, Any],
    migration: dict[str, Any] | None,
    expected_repository_id: int,
) -> tuple[dict[str, Any], str]:
    observed = metadata.get("full_name")
    message = (
        "canonical repository name mismatch: "
        f"expected {repo}, received {observed!r}"
    )
    return (
        {
            "repository": repo,
            "status": "BLOCKED",
            "error": message,
            "repository_id": metadata.get("id"),
            "expected_repository_id": expected_repository_id,
            "observed_full_name": observed,
            "target_repository_after_cutover": (
                migration.get("target_repository_after_cutover")
                if migration
                else None
            ),
            "rename_status": migration.get("status") if migration else None,
            "canonical_role": role(repo, migration),
        },
        message,
    )


def capture_repository(
    repo: str,
    migration: dict[str, Any] | None,
    expected_repository_id: int | None,
    blockers: list[str],
    pr_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Require both stable ID and canonical full name for governed repositories."""

    metadata, error = gh(endpoint(repo))
    if (
        error is None
        and expected_repository_id is not None
        and isinstance(metadata, dict)
        and metadata.get("full_name") != repo
    ):
        record, mismatch = canonical_name_mismatch_record(
            repo,
            metadata,
            migration,
            expected_repository_id,
        )
        blockers.append(f"- `{repo}` metadata: {mismatch}")
        return record

    original_core_gh = CORE.gh
    replayed = False

    def replay_first_metadata(
        path: str,
        *,
        paginate: bool = False,
    ) -> tuple[Any | None, str | None]:
        nonlocal replayed
        if not replayed and not paginate and path == endpoint(repo):
            replayed = True
            return metadata, error
        return gh(path, paginate=paginate)

    CORE.gh = replay_first_metadata
    try:
        return CORE.capture_repository(
            repo,
            migration,
            expected_repository_id,
            blockers,
            pr_rows,
        )
    finally:
        CORE.gh = original_core_gh


def operational_blocker_lines() -> list[str]:
    return [
        f"- `{owner}`: {detail} Evidence: `{evidence}`"
        for owner, detail, evidence in OPERATIONAL_BLOCKERS
    ]


def merge_operational_blockers(blockers: list[str]) -> None:
    for line in operational_blocker_lines():
        if line not in blockers:
            blockers.append(line)


def write_outputs(
    captured_at: str,
    inventory: list[dict[str, Any]],
    pr_rows: list[dict[str, Any]],
    blockers: list[str],
) -> None:
    """Never let a clean API capture erase active non-API release blockers."""

    merge_operational_blockers(blockers)
    CORE.OUT = OUT
    CORE.write_outputs(captured_at, inventory, pr_rows, blockers)


def main() -> None:
    aliases = load_repository_aliases()
    exporter = load_postgres_exporter_authority()

    missing = set(aliases) - set(KNOWN_REPOSITORIES)
    if missing:
        raise SystemExit(
            "repository-review inventory omits rename-controlled repositories: "
            + ", ".join(sorted(missing))
        )
    if exporter["repository"] not in KNOWN_REPOSITORIES:
        raise SystemExit(
            "repository-review inventory omits PostgreSQL Exporter authority"
        )

    expected_ids = configured_repository_ids(aliases, exporter)
    OUT.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat()
    inventory: list[dict[str, Any]] = []
    pr_rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for repo in KNOWN_REPOSITORIES:
        inventory.append(
            capture_repository(
                repo,
                aliases.get(repo),
                expected_ids.get(repo),
                blockers,
                pr_rows,
            )
        )

    write_outputs(captured_at, inventory, pr_rows, blockers)
    print(f"REPOSITORIES={len(inventory)}")
    print(f"PULL_REQUESTS={len(pr_rows)}")
    print(f"BLOCKERS={len(blockers)}")


if __name__ == "__main__":
    main()
