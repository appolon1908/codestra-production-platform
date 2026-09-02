#!/usr/bin/env python3
"""Capture sanitized, fail-closed GitHub repository authority evidence."""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "repository-review"
ALIASES = ROOT / "config" / "repository-name-aliases.v1.json"
POSTGRES_EXPORTER_REPOSITORY = "appolon1908-hue/Codestra-Postgres-Exporter"
POSTGRES_EXPORTER_REPOSITORY_ID = 1350839865

KNOWN_REPOSITORIES = (
    "appolon1908-hue/codestra-production-platform",
    "appolon1908-hue/codestra-production-runtime-authority",
    "appolon1908-hue/Infustruction-repo",
    "appolon1908-hue/documentaions",
    "appolon1908-hue/Caddy",
    "appolon1908-hue/Kong",
    "appolon1908-hue/Keycloak",
    "appolon1908-hue/Middleware-",
    "Codestra-SRL/codestra-middleware",
    "appolon1908-hue/Odoo",
    "Codestra-SRL/codestra-odoo-addons",
    "appolon1908-hue/N8N",
    "appolon1908-hue/Codestra-Marketing-",
    "appolon1908-hue/Codestra-AI",
    "appolon1908-hue/Codestra-Communication-CC",
    "appolon1908-hue/Codesrea-Social-",
    "appolon1908-hue/social.codestra.co",
    "appolon1908-hue/codestra-provisioning-service",
    "appolon1908-hue/SDK-repository",
    "appolon1908-hue/communication-platform-",
    "appolon1908-hue/codestra",
    "appolon1908-hue/codestra-backend",
    "appolon1908-hue/backend2",
    "appolon1908-hue/Frontend-Resturant-",
    "appolon1908-hue/transportaion-Frontend",
    "appolon1908-hue/LARIM-A-Fornt-end",
    "appolon1908-hue/Codestra-OpenBao",
    "appolon1908-hue/Codestra-Prometheus",
    "appolon1908-hue/Codestra-Grafana-",
    "appolon1908-hue/Codestra-Alertmanager",
    "appolon1908-hue/Codestra-Loki",
    "appolon1908-hue/Codestra-Tempo",
    "appolon1908-hue/Codestra-Telemetry",
    "appolon1908-hue/Codestra-Alloy",
    "appolon1908-hue/Codestra-Node-Exporter",
    "appolon1908-hue/Codestra-cAdvisor",
    "appolon1908-hue/Codestra-Redis-Exporter",
    "appolon1908-hue/Codestra-Blackbox-Exporter",
    POSTGRES_EXPORTER_REPOSITORY,
    "appolon1908-hue/Superset",
)


def gh(path: str, *, paginate: bool = False) -> tuple[Any | None, str | None]:
    command = ["gh", "api"]
    if paginate:
        command.append("--paginate")
    command.append(path)
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        message = result.stderr.strip().splitlines()
        return None, message[-1] if message else "GitHub API request failed"
    try:
        if paginate:
            values: list[Any] = []
            decoder = json.JSONDecoder()
            text = result.stdout.lstrip()
            while text:
                value, offset = decoder.raw_decode(text)
                values.extend(value if isinstance(value, list) else [value])
                text = text[offset:].lstrip()
            return values, None
        return json.loads(result.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def endpoint(repo: str, suffix: str = "") -> str:
    return f"repos/{repo}{suffix}"


def load_authority_document() -> dict[str, Any]:
    try:
        document = json.loads(ALIASES.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"invalid repository alias manifest: {exc}") from exc
    if not isinstance(document, dict):
        raise SystemExit("repository alias manifest root must be an object")
    if document.get("schema_version") != "1.0":
        raise SystemExit("repository alias schema_version must be 1.0")
    if document.get("status") != "PREPARED_NOT_RENAMED":
        raise SystemExit(
            "repository aliases must remain PREPARED_NOT_RENAMED before cutover"
        )
    if document.get("identity_key") != "repository_id":
        raise SystemExit("repository_id must be the stable repository identity")
    if document.get("historical_evidence_immutable") is not True:
        raise SystemExit("historical repository evidence must remain immutable")
    return document


def load_repository_aliases() -> dict[str, dict[str, Any]]:
    """Return validated rename mappings without coupling them to a test inventory."""

    document = load_authority_document()
    mappings = document.get("mappings")
    if not isinstance(mappings, list) or len(mappings) != 6:
        raise SystemExit("repository alias manifest must contain exactly six mappings")

    by_current: dict[str, dict[str, Any]] = {}
    ids: set[int] = set()
    targets: set[str] = set()
    for item in mappings:
        if not isinstance(item, dict):
            raise SystemExit("repository alias mapping must be an object")
        repository_id = item.get("repository_id")
        current = item.get("current_repository")
        target = item.get("target_repository_after_cutover")
        status = item.get("status")
        if not isinstance(repository_id, int) or repository_id <= 0:
            raise SystemExit("repository alias contains an invalid repository ID")
        if repository_id in ids:
            raise SystemExit(
                f"duplicate repository ID in alias manifest: {repository_id}"
            )
        if not isinstance(current, str) or not current.startswith("appolon1908-hue/"):
            raise SystemExit(f"invalid current repository in alias manifest: {current}")
        if not isinstance(target, str) or not target.startswith("appolon1908-hue/"):
            raise SystemExit(f"invalid target repository in alias manifest: {target}")
        if current == target:
            raise SystemExit(
                f"current and target repository names are identical: {current}"
            )
        if current in by_current or target in targets:
            raise SystemExit("duplicate current or target repository in alias manifest")
        if status != "PREPARED_NOT_RENAMED":
            raise SystemExit(
                f"repository alias changed state without cutover: {current}"
            )
        ids.add(repository_id)
        targets.add(target)
        by_current[current] = item
    return by_current


def load_postgres_exporter_authority() -> dict[str, Any]:
    document = load_authority_document()
    exporter = document.get("postgres_exporter_authority")
    if not isinstance(exporter, dict):
        raise SystemExit("PostgreSQL Exporter authority is missing")
    expected = {
        "repository_id": POSTGRES_EXPORTER_REPOSITORY_ID,
        "repository": POSTGRES_EXPORTER_REPOSITORY,
        "public_hostname": None,
        "private_service_identity": "postgres-exporter:9187",
        "forbidden_public_hostname": "pgex.codestra.media",
        "exposure": "PRIVATE_INTERNAL_ONLY",
    }
    for key, value in expected.items():
        if exporter.get(key) != value:
            raise SystemExit(f"PostgreSQL Exporter authority field is invalid: {key}")
    return exporter


def configured_repository_ids(
    aliases: dict[str, dict[str, Any]],
    exporter: dict[str, Any],
) -> dict[str, int]:
    values = {
        repository: int(mapping["repository_id"])
        for repository, mapping in aliases.items()
    }
    exporter_repo = exporter["repository"]
    exporter_id = int(exporter["repository_id"])
    if exporter_repo in values and values[exporter_repo] != exporter_id:
        raise SystemExit("conflicting PostgreSQL Exporter stable repository IDs")
    values[exporter_repo] = exporter_id
    return values


def role(repo: str, alias: dict[str, Any] | None = None) -> str:
    name = repo.split("/", 1)[1].lower()
    repository_id = alias.get("repository_id") if alias else None
    if name == "codestra-production-platform":
        return "PROTECTED_RELEASE_AUTHORITY"
    if name == "codestra-production-runtime-authority":
        return "ADOPTED_ORPHAN_RUNTIME_AUTHORITY"
    if repository_id == 1350724865:
        return "INFRASTRUCTURE_AND_CERTIFICATION_AUTHORITY"
    if repository_id == 1350724356:
        return "CROSS_REPOSITORY_DOCUMENTATION_AUTHORITY"
    if repository_id == 1351353723:
        return "SOCIAL_CONTROL_PLANE_ARCHITECTURE"
    if repository_id in {1221155447, 1343761049, 1343962199}:
        return "INDEPENDENT_PRODUCT_FRONTEND"
    if repo == POSTGRES_EXPORTER_REPOSITORY:
        return "PRIVATE_POSTGRESQL_METRICS_EXPORTER_AUTHORITY"
    if name in {"sdk-repository", "codestra"}:
        return "PLATFORM_CONTRACT_OR_CLIENT_SOURCE"
    return "SERVICE_SOURCE_CANDIDATE_REQUIRES_OWNER_CONFIRMATION"


def metadata_blocked_record(
    repo: str,
    error: str,
    migration: dict[str, Any] | None,
    expected_repository_id: int | None,
) -> dict[str, Any]:
    return {
        "repository": repo,
        "status": "BLOCKED",
        "error": error,
        "repository_id": None,
        "expected_repository_id": expected_repository_id,
        "target_repository_after_cutover": (
            migration.get("target_repository_after_cutover") if migration else None
        ),
        "rename_status": migration.get("status") if migration else None,
        "canonical_role": role(repo, migration),
    }


def identity_mismatch_record(
    repo: str,
    metadata: dict[str, Any],
    migration: dict[str, Any] | None,
    expected_repository_id: int,
) -> tuple[dict[str, Any], str]:
    message = (
        "stable repository ID mismatch: "
        f"expected {expected_repository_id}, received {metadata.get('id')}"
    )
    return (
        {
            "repository": repo,
            "status": "BLOCKED",
            "error": message,
            "repository_id": metadata.get("id"),
            "expected_repository_id": expected_repository_id,
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
    metadata, error = gh(endpoint(repo))
    if error:
        blockers.append(f"- `{repo}` metadata: {error}")
        return metadata_blocked_record(
            repo,
            error,
            migration,
            expected_repository_id,
        )
    if not isinstance(metadata, dict):
        error = "GitHub metadata response was not an object"
        blockers.append(f"- `{repo}` metadata: {error}")
        return metadata_blocked_record(
            repo,
            error,
            migration,
            expected_repository_id,
        )

    if (
        expected_repository_id is not None
        and metadata.get("id") != expected_repository_id
    ):
        record, mismatch = identity_mismatch_record(
            repo,
            metadata,
            migration,
            expected_repository_id,
        )
        blockers.append(f"- `{repo}` metadata: {mismatch}")
        return record

    branches, branches_error = gh(
        endpoint(repo, "/branches?per_page=100"),
        paginate=True,
    )
    prs, prs_error = gh(
        endpoint(repo, "/pulls?state=all&per_page=100"),
        paginate=True,
    )
    rulesets, rulesets_error = gh(
        endpoint(repo, "/rulesets?per_page=100"),
        paginate=True,
    )
    workflows, workflows_error = gh(endpoint(repo, "/actions/workflows?per_page=100"))
    runs, runs_error = gh(endpoint(repo, "/actions/runs?per_page=20"))
    releases, releases_error = gh(endpoint(repo, "/releases?per_page=20"))

    codeowners_present = False
    for candidate in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        value, _ = gh(
            endpoint(repo, f"/contents/{candidate}?ref={metadata.get('default_branch')}")
        )
        if value:
            codeowners_present = True
            break

    alerts: dict[str, Any] = {}
    for alert_name, path in (
        ("dependabot", "/dependabot/alerts?state=open&per_page=100"),
        ("secret_scanning", "/secret-scanning/alerts?state=open&per_page=100"),
        ("code_scanning", "/code-scanning/alerts?state=open&per_page=100"),
    ):
        value, alert_error = gh(endpoint(repo, path), paginate=True)
        alerts[alert_name] = {"count": len(value or []), "error": alert_error}
        if alert_error:
            blockers.append(f"- `{repo}` {alert_name} security alerts: {alert_error}")

    for label, value in (
        ("branches", branches_error),
        ("pull_requests", prs_error),
        ("rulesets", rulesets_error),
        ("workflows", workflows_error),
        ("workflow_runs", runs_error),
        ("releases", releases_error),
    ):
        if value:
            blockers.append(f"- `{repo}` {label}: {value}")

    branch_rows = branches if isinstance(branches, list) else []
    pr_values = prs if isinstance(prs, list) else []
    ruleset_values = rulesets if isinstance(rulesets, list) else []
    run_values = (
        runs.get("workflow_runs", []) if isinstance(runs, dict) else []
    )
    workflow_values = (
        workflows.get("workflows", []) if isinstance(workflows, dict) else []
    )
    release_values = releases if isinstance(releases, list) else []

    for pr in pr_values:
        if not isinstance(pr, dict):
            continue
        pr_rows.append(
            {
                "repository": repo,
                "number": pr.get("number"),
                "state": pr.get("state"),
                "draft": pr.get("draft"),
                "title": pr.get("title"),
                "head_sha": (pr.get("head") or {}).get("sha"),
                "base": (pr.get("base") or {}).get("ref"),
                "merge_commit_sha": pr.get("merge_commit_sha"),
                "updated_at": pr.get("updated_at"),
                "url": pr.get("html_url"),
            }
        )

    return {
        "repository": repo,
        "repository_id": metadata.get("id"),
        "expected_repository_id": expected_repository_id,
        "target_repository_after_cutover": (
            migration.get("target_repository_after_cutover") if migration else None
        ),
        "rename_status": migration.get("status") if migration else None,
        "status": "CAPTURED",
        "visibility": metadata.get("visibility"),
        "archived": metadata.get("archived"),
        "default_branch": metadata.get("default_branch"),
        "html_url": metadata.get("html_url"),
        "pushed_at": metadata.get("pushed_at"),
        "open_issues_count": metadata.get("open_issues_count"),
        "canonical_role": role(repo, migration),
        "codeowners_present": codeowners_present,
        "branches": [
            {
                "name": item.get("name"),
                "sha": (item.get("commit") or {}).get("sha"),
                "protected": item.get("protected"),
            }
            for item in branch_rows
            if isinstance(item, dict)
        ],
        "rulesets": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "enforcement": item.get("enforcement"),
                "target": item.get("target"),
            }
            for item in ruleset_values
            if isinstance(item, dict)
        ],
        "workflows": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "state": item.get("state"),
            }
            for item in workflow_values
            if isinstance(item, dict)
        ],
        "latest_workflow_runs": [
            {
                "name": item.get("name"),
                "head_sha": item.get("head_sha"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "html_url": item.get("html_url"),
            }
            for item in run_values
            if isinstance(item, dict)
        ],
        "latest_releases": [
            {
                "tag_name": item.get("tag_name"),
                "target": item.get("target_commitish"),
                "published_at": item.get("published_at"),
                "html_url": item.get("html_url"),
            }
            for item in release_values
            if isinstance(item, dict)
        ],
        "security_alerts": alerts,
    }


def write_outputs(
    captured_at: str,
    inventory: list[dict[str, Any]],
    pr_rows: list[dict[str, Any]],
    blockers: list[str],
) -> None:
    payload = {
        "schema_version": 2,
        "captured_at": captured_at,
        "repository_identity_key": "repository_id",
        "rename_manifest_status": "PREPARED_NOT_RENAMED",
        "repositories": inventory,
    }
    (OUT / "REPOSITORY-INVENTORY.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    fields = (
        "repository",
        "number",
        "state",
        "draft",
        "title",
        "head_sha",
        "base",
        "merge_commit_sha",
        "updated_at",
        "url",
    )
    with (OUT / "REPOSITORY-PR-MATRIX.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            sorted(
                pr_rows,
                key=lambda row: (row["repository"], -(row["number"] or 0)),
            )
        )

    authority = {
        "schema_version": 2,
        "captured_at": captured_at,
        "status": "REVIEW_REQUIRED",
        "repository_identity_key": "repository_id",
        "rename_manifest_status": "PREPARED_NOT_RENAMED",
        "repositories": [
            {
                "repository": item["repository"],
                "capture_status": item.get("status"),
                "capture_error": item.get("error"),
                "repository_id": item.get("repository_id"),
                "expected_repository_id": item.get("expected_repository_id"),
                "target_repository_after_cutover": item.get(
                    "target_repository_after_cutover"
                ),
                "rename_status": item.get("rename_status"),
                "canonical_role": item.get("canonical_role", "ACCESS_BLOCKED"),
                "source_authority": "PENDING_PROTECTED_OWNER_REVIEW",
                "database_authority": "PENDING_PROTECTED_OWNER_REVIEW",
                "release_authority": "appolon1908-hue/codestra-production-platform",
                "runtime_authority": "PENDING_RUNTIME_RECONCILIATION",
                "security_owner": "PENDING_OWNER_ASSIGNMENT",
                "business_owner": "PENDING_OWNER_ASSIGNMENT",
            }
            for item in inventory
        ],
    }
    (OUT / "REPOSITORY-AUTHORITY-MATRIX.yaml").write_text(
        yaml.safe_dump(authority, sort_keys=False, width=120),
        encoding="utf-8",
    )

    blocker_text = [
        "# Repository Review Blockers",
        "",
        f"Captured: {captured_at}",
        "",
        (
            "A missing permission, unavailable API, or repository-ID mismatch "
            "is a blocker, never a PASS."
        ),
        "",
    ] + (blockers or ["- None observed during API capture."])
    (OUT / "REPOSITORY-BLOCKERS.md").write_text(
        "\n".join(blocker_text) + "\n",
        encoding="utf-8",
    )


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
