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
KNOWN_REPOSITORIES = (
    "appolon1908-hue/codestra-production-platform",
    "appolon1908-hue/codestra-production-runtime-authority",
    "appolon1908-hue/Infustruction-repo",
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


def role(repo: str) -> str:
    name = repo.split("/", 1)[1].lower()
    if name == "codestra-production-platform":
        return "PROTECTED_RELEASE_AUTHORITY"
    if name == "codestra-production-runtime-authority":
        return "ADOPTED_ORPHAN_RUNTIME_AUTHORITY"
    if name == "infustruction-repo":
        return "INFRASTRUCTURE_AND_CERTIFICATION_AUTHORITY"
    if name in {"sdk-repository", "codestra"}:
        return "PLATFORM_CONTRACT_OR_CLIENT_SOURCE"
    return "SERVICE_SOURCE_CANDIDATE_REQUIRES_OWNER_CONFIRMATION"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat()
    inventory: list[dict[str, Any]] = []
    pr_rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for repo in KNOWN_REPOSITORIES:
        metadata, error = gh(endpoint(repo))
        if error:
            inventory.append({"repository": repo, "status": "BLOCKED", "error": error})
            blockers.append(f"- `{repo}` metadata: {error}")
            continue

        branches, branches_error = gh(endpoint(repo, "/branches?per_page=100"), paginate=True)
        prs, prs_error = gh(endpoint(repo, "/pulls?state=all&per_page=100"), paginate=True)
        rulesets, rulesets_error = gh(endpoint(repo, "/rulesets?per_page=100"), paginate=True)
        workflows, workflows_error = gh(endpoint(repo, "/actions/workflows?per_page=100"))
        runs, runs_error = gh(endpoint(repo, "/actions/runs?per_page=20"))
        releases, releases_error = gh(endpoint(repo, "/releases?per_page=20"))
        codeowners_present = False
        for candidate in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
            value, _ = gh(endpoint(repo, f"/contents/{candidate}?ref={metadata.get('default_branch')}"))
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
            ("branches", branches_error), ("pull_requests", prs_error),
            ("rulesets", rulesets_error), ("workflows", workflows_error),
            ("workflow_runs", runs_error), ("releases", releases_error),
        ):
            if value:
                blockers.append(f"- `{repo}` {label}: {value}")

        branch_rows = branches or []
        pr_values = prs or []
        run_values = (runs or {}).get("workflow_runs", []) if isinstance(runs, dict) else []
        workflow_values = (workflows or {}).get("workflows", []) if isinstance(workflows, dict) else []
        release_values = releases or []
        inventory.append({
            "repository": repo,
            "status": "CAPTURED",
            "visibility": metadata.get("visibility"),
            "archived": metadata.get("archived"),
            "default_branch": metadata.get("default_branch"),
            "html_url": metadata.get("html_url"),
            "pushed_at": metadata.get("pushed_at"),
            "open_issues_count": metadata.get("open_issues_count"),
            "canonical_role": role(repo),
            "codeowners_present": codeowners_present,
            "branches": [{"name": x.get("name"), "sha": (x.get("commit") or {}).get("sha"), "protected": x.get("protected")} for x in branch_rows],
            "rulesets": [{"id": x.get("id"), "name": x.get("name"), "enforcement": x.get("enforcement"), "target": x.get("target")} for x in (rulesets or [])],
            "workflows": [{"name": x.get("name"), "path": x.get("path"), "state": x.get("state")} for x in workflow_values],
            "latest_workflow_runs": [{"name": x.get("name"), "head_sha": x.get("head_sha"), "status": x.get("status"), "conclusion": x.get("conclusion"), "html_url": x.get("html_url")} for x in run_values],
            "latest_releases": [{"tag_name": x.get("tag_name"), "target": x.get("target_commitish"), "published_at": x.get("published_at"), "html_url": x.get("html_url")} for x in release_values],
            "security_alerts": alerts,
        })
        for pr in pr_values:
            pr_rows.append({
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
            })

    payload = {"schema_version": 1, "captured_at": captured_at, "repositories": inventory}
    (OUT / "REPOSITORY-INVENTORY.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    fields = ("repository", "number", "state", "draft", "title", "head_sha", "base", "merge_commit_sha", "updated_at", "url")
    with (OUT / "REPOSITORY-PR-MATRIX.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(pr_rows, key=lambda row: (row["repository"], -(row["number"] or 0))))

    authority = {
        "schema_version": 1,
        "captured_at": captured_at,
        "status": "REVIEW_REQUIRED",
        "repositories": [{
            "repository": item["repository"],
            "canonical_role": item.get("canonical_role", "ACCESS_BLOCKED"),
            "source_authority": "PENDING_PROTECTED_OWNER_REVIEW",
            "database_authority": "PENDING_PROTECTED_OWNER_REVIEW",
            "release_authority": "appolon1908-hue/codestra-production-platform",
            "runtime_authority": "PENDING_RUNTIME_RECONCILIATION",
            "security_owner": "PENDING_OWNER_ASSIGNMENT",
            "business_owner": "PENDING_OWNER_ASSIGNMENT",
        } for item in inventory],
    }
    (OUT / "REPOSITORY-AUTHORITY-MATRIX.yaml").write_text(yaml.safe_dump(authority, sort_keys=False, width=120))
    blocker_text = [
        "# Repository Review Blockers", "", f"Captured: {captured_at}", "",
        "A missing permission or unavailable API is a blocker, never a PASS.", "",
    ] + (blockers or ["- None observed during API capture."])
    (OUT / "REPOSITORY-BLOCKERS.md").write_text("\n".join(blocker_text) + "\n")
    print(f"REPOSITORIES={len(inventory)}")
    print(f"PULL_REQUESTS={len(pr_rows)}")
    print(f"BLOCKERS={len(blockers)}")


if __name__ == "__main__":
    main()
