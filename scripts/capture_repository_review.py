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
    "appolon1908-hue/Codestra-Postgres-Exporter",
    "appolon1908-hue/Superset",
)


def gh(path: str, *, paginate: bool = False) -> tuple[Any | None, str | None]:
    command = ["gh", "api"]
    if paginate:
        command.append("--paginate")
    command.append(path)
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        return None, result.stderr.strip().splitlines()[-1]
    try:
        if paginate:
            values = []
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


def load_repository_aliases() -> dict[str, dict[str, Any]]:
    try:
        document = json.loads(ALIASES.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"invalid repository alias manifest: {exc}") from exc

    if document.get("schema_version") != "1.0":
        raise SystemExit("repository alias schema_version must be 1.0")
    if document.get("status") != "PREPARED_NOT_RENAMED":
        raise SystemExit("repository aliases must remain PREPARED_NOT_RENAMED before cutover")
    if document.get("identity_key") != "repository_id":
        raise SystemExit("repository_id must be the stable repository identity")
    if document.get("historical_evidence_immutable") is not True:
        raise SystemExit("historical repository evidence must remain immutable")

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
            raise SystemExit(f"duplicate repository ID in alias manifest: {repository_id}")
        if not isinstance(current, str) or not current.startswith("appolon1908-hue/"):
            raise SystemExit(f"invalid current repository in alias manifest: {current}")
        if not isinstance(target, str) or not target.startswith("appolon1908-hue/"):
            raise SystemExit(f"invalid target repository in alias manifest: {target}")
        if current == target:
            raise SystemExit(f"current and target repository names are identical: {current}")
        if current in by_current or target in targets:
            raise SystemExit("duplicate current or target repository in alias manifest")
        if status != "PREPARED_NOT_RENAMED":
            raise SystemExit(f"repository alias changed state without cutover: {current}")
        ids.add(repository_id)
        targets.add(target)
        by_current[current] = item

    missing = set(by_current) - set(KNOWN_REPOSITORIES)
    if missing:
        raise SystemExit(
            "repository-review inventory omits rename-controlled repositories: "
            + ", ".join(sorted(missing))
        )
    return by_current


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
    if name in {"sdk-repository", "codestra"}:
        return "PLATFORM_CONTRACT_OR_CLIENT_SOURCE"
    return "SERVICE_SOURCE_CANDIDATE_REQUIRES_OWNER_CONFIRMATION"


def main() -> None:
    aliases = load_repository_aliases()
    OUT.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat()
    inventory: list[dict[str, Any]] = []
    pr_rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for repo in KNOWN_REPOSITORIES:
        migration = aliases.get(repo)
        metadata, error = gh(endpoint(repo))
        if error:
            inventory.append(
                {
                    "repository": repo,
                    "status": "BLOCKED",
                    "error": error,
                    "repository_id": migration.get("repository_id") if migration else None,
                    "target_repository_after_cutover": (
                        migration.get("target_repository_after_cutover")
                        if migration
                        else None
                    ),
                    "rename_status": migration.get("status") if migration else None,
                }
            )
            blockers.append(f"- `{repo}` metadata: {error}")
            continue

        if migration and metadata.get("id") != migration["repository_id"]:
            message = (
                "stable repository ID mismatch: "
                f"expected {migration['repository_id']}, received {metadata.get('id')}"
            )
            inventory.append(
                {
                    "repository": repo,
                    "status": "BLOCKED",
                    "error": message,
                    "repository_id": metadata.get("id"),
                    "expected_repository_id": migration["repository_id"],
                    "target_repository_after_cutover": migration[
                        "target_repository_after_cutover"
                    ],
                    "rename_status": migration["status"],
                }
            )
            blockers.append(f"- `{repo}` metadata: {message}")
            continue

        branches, branches_error = gh(endpoint(repo, "/branches?per_page=100"), paginate=True)
        prs, prs_error = gh(endpoint(repo, "/pulls?state=all&per_page=100"), paginate=True)
        rulesets, rulesets_error = gh(endpoint(repo, "/rulesets?per_page=100"), paginate=True)
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
                blockers.append(
                    f"- `{repo}` {alert_name} security alerts: {alert_error}"
                )

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

        branch_rows = branches or []
        pr_values = prs or []
        run_values = (
            (runs or {}).get("workflow_runs", []) if isinstance(runs, dict) else []
        )
        workflow_values = (
            (workflows or {}).get("workflows", [])
            if isinstance(workflows, dict)
            else []
        )
        release_values = releases or []
        inventory.append(
            {
                "repository": repo,
                "repository_id": metadata.get("id"),
                "expected_repository_id": (
                    migration.get("repository_id") if migration else metadata.get("id")
                ),
                "target_repository_after_cutover": (
                    migration.get("target_repository_after_cutover")
                    if migration
                    else None
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
                        "name": x.get("name"),
                        "sha": (x.get("commit") or {}).get("sha"),
                        "protected": x.get("protected"),
                    }
                    for x in branch_rows
                ],
                "rulesets": [
                    {
                        "id": x.get("id"),
                        "name": x.get("name"),
                        "enforcement": x.get("enforcement"),
                        "target": x.get("target"),
                    }
                    for x in (rulesets or [])
                ],
                "workflows": [
                    {
                        "name": x.get("name"),
                        "path": x.get("path"),
                        "state": x.get("state"),
                    }
                    for x in workflow_values
                ],
                "latest_workflow_runs": [
                    {
                        "name": x.get("name"),
                        "head_sha": x.get("head_sha"),
                        "status": x.get("status"),
                        "conclusion": x.get("conclusion"),
                        "html_url": x.get("html_url"),
                    }
                    for x in run_values
                ],
                "latest_releases": [
                    {
                        "tag_name": x.get("tag_name"),
                        "target": x.get("target_commitish"),
                        "published_at": x.get("published_at"),
                        "html_url": x.get("html_url"),
                    }
                    for x in release_values
                ],
                "security_alerts": alerts,
            }
        )
        for pr in pr_values:
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

    payload = {
        "schema_version": 2,
        "captured_at": captured_at,
        "repository_identity_key": "repository_id",
        "rename_manifest_status": "PREPARED_NOT_RENAMED",
        "repositories": inventory,
    }
    (OUT / "REPOSITORY-INVENTORY.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
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
    with (OUT / "REPOSITORY-PR-MATRIX.csv").open("w", newline="") as handle:
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
        yaml.safe_dump(authority, sort_keys=False, width=120)
    )
    blocker_text = [
        "# Repository Review Blockers",
        "",
        f"Captured: {captured_at}",
        "",
        "A missing permission, unavailable API, or repository-ID mismatch is a blocker, never a PASS.",
        "",
    ] + (blockers or ["- None observed during API capture."])
    (OUT / "REPOSITORY-BLOCKERS.md").write_text("\n".join(blocker_text) + "\n")
    print(f"REPOSITORIES={len(inventory)}")
    print(f"PULL_REQUESTS={len(pr_rows)}")
    print(f"BLOCKERS={len(blockers)}")


if __name__ == "__main__":
    main()
