#!/usr/bin/env python3
"""Audit repository/ref/SHA tuples in PRODUCTION-SOURCE-LOCK.yaml against GitHub."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "PRODUCTION-SOURCE-LOCK.yaml"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_KEYS = ("repository", "repo", "source_repository", "github_repository")
REF_KEYS = ("branch", "ref", "source_branch", "protected_branch", "target_branch")
SHA_KEYS = ("sha", "source_sha", "commit_sha", "git_sha", "revision", "source_commit", "protected_source_sha")


def fail(message: str) -> None:
    print(f"PRODUCTION_SOURCE_REMOTE_AUDIT_ERROR={message}", file=sys.stderr)
    raise SystemExit(1)


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        fail(f"cannot parse {path}: {exc}")


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def first(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    normalized = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        if key in normalized:
            return normalized[key]
    return None


def normalize_ref(value: Any) -> str:
    text = str(value or "").strip()
    for prefix in ("refs/heads/", "heads/"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def extract_authorities(document: Any) -> list[dict[str, str]]:
    authorities: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for path, value in walk(document):
        if not isinstance(value, dict):
            continue
        repository = str(first(value, REPOSITORY_KEYS) or "").strip()
        branch = normalize_ref(first(value, REF_KEYS))
        sha = str(first(value, SHA_KEYS) or "").strip().lower()
        if not REPOSITORY_RE.fullmatch(repository) or not branch:
            continue
        key = (repository.lower(), branch, sha)
        if key in seen:
            continue
        seen.add(key)
        authorities.append(
            {
                "path": path,
                "repository": repository,
                "branch": branch,
                "recorded_sha": sha,
            }
        )
    authorities.sort(key=lambda item: (item["repository"].lower(), item["branch"], item["path"]))
    return authorities


class NoGitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise RuntimeError("GitHub redirect rejected")


def github_request(path: str, token: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "codestra-production-source-lock-auditor",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    try:
        with urllib.request.build_opener(NoGitHubRedirect()).open(request, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("GitHub transport failure") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("GitHub returned malformed JSON") from exc


def resolve_ref(repository: str, branch: str, token: str) -> str:
    encoded = urllib.parse.quote(branch, safe="")
    payload = github_request(f"/repos/{repository}/git/ref/heads/{encoded}", token)
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub ref response is not an object")
    obj = payload.get("object")
    if (payload.get("ref") != f"refs/heads/{branch}" or not isinstance(obj, dict)
            or obj.get("type") != "commit"):
        raise RuntimeError("GitHub ref response does not match the requested branch commit")
    sha = obj.get("sha")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise RuntimeError("GitHub ref response lacks a full commit SHA")
    return sha


def workflow_sha_binding(
    authority: dict[str, str],
    remote_sha: str,
    *,
    repository: str,
    ref: str,
    sha: str,
) -> bool:
    """Bind a self-referential protected branch to GitHub's exact run SHA.

    A commit cannot contain its own SHA.  The source lock therefore leaves the
    platform SHA empty and relies on protected-release provenance.  Accept that
    representation only for the repository and branch executing this workflow,
    and only after the GitHub API independently resolves the branch to the same
    full commit SHA.  Pull-request refs and any non-empty invalid recorded SHA
    remain mismatches.
    """

    workflow_sha = sha.strip().lower()
    return bool(
        authority["recorded_sha"] == ""
        and authority["repository"].lower() == repository.strip().lower()
        and authority["branch"] == normalize_ref(ref)
        and SHA_RE.fullmatch(workflow_sha)
        and remote_sha == workflow_sha
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-match", action="store_true")
    args = parser.parse_args()

    authorities = extract_authorities(load_yaml(args.lock))
    if not authorities:
        fail("no repository/ref authorities were discovered in the source lock")
    token = os.environ.get("GITHUB_TOKEN", "")
    workflow_repository = os.environ.get("GITHUB_REPOSITORY", "")
    workflow_ref = os.environ.get("GITHUB_REF", "")
    workflow_sha = os.environ.get("GITHUB_SHA", "")
    results: list[dict[str, Any]] = []
    for authority in authorities:
        record: dict[str, Any] = dict(authority)
        try:
            remote = resolve_ref(authority["repository"], authority["branch"], token)
            record["remote_sha"] = remote
            record["recorded_sha_valid"] = bool(SHA_RE.fullmatch(authority["recorded_sha"]))
            workflow_bound = workflow_sha_binding(
                authority,
                remote,
                repository=workflow_repository,
                ref=workflow_ref,
                sha=workflow_sha,
            )
            record["workflow_sha_bound"] = workflow_bound
            record["effective_sha"] = (
                authority["recorded_sha"]
                if record["recorded_sha_valid"]
                else workflow_sha.strip().lower() if workflow_bound else None
            )
            record["identity_source"] = (
                "recorded_sha"
                if record["recorded_sha_valid"]
                else "github_workflow_exact_sha" if workflow_bound else None
            )
            record["matches"] = bool(
                (record["recorded_sha_valid"] and authority["recorded_sha"] == remote)
                or workflow_bound
            )
            record["status"] = "PASS" if record["matches"] else "MISMATCH"
        except RuntimeError as exc:
            record["remote_sha"] = None
            record["recorded_sha_valid"] = bool(SHA_RE.fullmatch(authority["recorded_sha"]))
            record["workflow_sha_bound"] = False
            record["effective_sha"] = None
            record["identity_source"] = None
            record["matches"] = False
            record["status"] = "ERROR"
            record["error"] = str(exc)
        results.append(record)

    mismatches = [record for record in results if record["status"] != "PASS"]
    report = {
        "schema_version": 1,
        "lock": str(args.lock),
        "authority_count": len(results),
        "pass_count": len(results) - len(mismatches),
        "mismatch_count": len(mismatches),
        "status": "PASS" if not mismatches else "BLOCKED",
        "authorities": results,
        "lock_updated": False,
        "deployment_authorized": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PRODUCTION_SOURCE_REMOTE_AUTHORITIES={len(results)}")
    print(f"PRODUCTION_SOURCE_REMOTE_MISMATCHES={len(mismatches)}")
    print(f"PRODUCTION_SOURCE_REMOTE_AUDIT={report['status']}")
    if args.require_match and mismatches:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
