#!/usr/bin/env python3
"""Configure the GitHub ``staging-readonly`` environment fail closed.

This tool performs only repository-account configuration:

* enable custom deployment branch policies;
* retain existing wait-timer/reviewer rules when GitHub exposes them;
* permit exactly ``release/production-activation`` to deploy;
* set only the two source-known environment constants: one-percent maximum
  canary traffic and the canonical 29-route Kong denominator.

It never creates credentials, reads secret values, connects to a server, or
changes staging/production runtime state. The caller must supply a
repository-scoped token with Administration:write and Environments:write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
REPOSITORY = "appolon1908-hue/codestra-production-platform"
ENVIRONMENT = "staging-readonly"
ALLOWED_BRANCH = "release/production-activation"
SAFE_VARIABLES = {
    "CODESTRA_STAGING_CANARY_MAX_PERCENT": "1",
    "CODESTRA_STAGING_KONG_ROUTE_COUNT": "29",
}
TOKEN_ENV = "CODESTRA_REPOSITORY_ADMIN_TOKEN"


class ConfigurationError(RuntimeError):
    """Fail-closed account-configuration error without token material."""


def api_request(
    method: str,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
    expected: set[int] | None = None,
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "codestra-staging-readonly-environment-configurator",
        "X-GitHub-Api-Version": API_VERSION,
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    accepted = expected or {200}
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            payload_bytes = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ConfigurationError(
            f"GitHub API {method} {path} failed with HTTP {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ConfigurationError(
            f"GitHub API {method} {path} transport failed: {exc}"
        ) from exc
    if status not in accepted:
        raise ConfigurationError(
            f"GitHub API {method} {path} returned unexpected HTTP {status}"
        )
    if not payload_bytes:
        return status, None
    try:
        return status, json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"GitHub API {method} {path} returned malformed JSON"
        ) from exc


def extract_protection_settings(environment: dict[str, Any]) -> dict[str, Any]:
    """Preserve existing supported wait/reviewer protection configuration."""

    has_wait_timer = False
    has_reviewers = False
    wait_timer = 0
    prevent_self_review = False
    reviewers: list[dict[str, Any]] = []
    rules = environment.get("protection_rules", [])
    if not isinstance(rules, list):
        raise ConfigurationError("cannot preserve malformed protection rules")
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
                raise ConfigurationError("cannot preserve malformed protection rule")
            if rule.get("type") == "wait_timer":
                if has_wait_timer:
                    raise ConfigurationError("duplicate wait-timer protection")
                has_wait_timer = True
                value = rule.get("wait_timer")
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    wait_timer = value
                else:
                    raise ConfigurationError("cannot preserve malformed wait-timer protection")
            elif rule.get("type") == "required_reviewers":
                if has_reviewers:
                    raise ConfigurationError("duplicate reviewer protection")
                has_reviewers = True
                prevent_self_review = rule.get("prevent_self_review", False)
                if type(prevent_self_review) is not bool:
                    raise ConfigurationError("malformed self-review protection")
                raw_reviewers = rule.get("reviewers")
                if not isinstance(raw_reviewers, list) or not raw_reviewers:
                    raise ConfigurationError("cannot preserve malformed reviewer protection")
                for item in raw_reviewers:
                    if not isinstance(item, dict):
                        raise ConfigurationError("cannot preserve malformed reviewer protection")
                    reviewer = item.get("reviewer")
                    if not isinstance(reviewer, dict):
                        reviewer = item
                    reviewer_id = reviewer.get("id")
                    reviewer_type = item.get("type") or reviewer.get("type")
                    if (
                        isinstance(reviewer_id, int)
                        and not isinstance(reviewer_id, bool)
                        and reviewer_id > 0
                        and reviewer_type in {"User", "Team"}
                    ):
                        reviewers.append(
                            {"type": reviewer_type, "id": reviewer_id}
                        )
                    else:
                        raise ConfigurationError("cannot preserve malformed reviewer protection")
    payload: dict[str, Any] = {
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
    }
    # Even null/false reviewer fields trigger plan entitlement validation on
    # private repositories. Omit absent rules; never retry by removing an
    # existing rule after an API error.
    if has_wait_timer:
        payload["wait_timer"] = wait_timer
    if has_reviewers:
        payload["prevent_self_review"] = prevent_self_review
        payload["reviewers"] = reviewers
    return payload


def upsert_environment_variable(token: str, name: str, value: str) -> None:
    encoded_environment = urllib.parse.quote(ENVIRONMENT, safe="")
    collection = (
        f"/repos/{REPOSITORY}/environments/{encoded_environment}/variables"
    )
    _, current = api_request(
        "GET",
        f"{collection}?per_page=30",
        token,
        expected={200},
    )
    entries = current.get("variables") if isinstance(current, dict) else None
    names = {
        item.get("name")
        for item in entries or []
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if name in names:
        api_request(
            "PATCH",
            f"{collection}/{urllib.parse.quote(name, safe='')}",
            token,
            body={"name": name, "value": value},
            expected={204},
        )
    else:
        api_request(
            "POST",
            collection,
            token,
            body={"name": name, "value": value},
            expected={201},
        )


def configure(token: str) -> dict[str, Any]:
    encoded_environment = urllib.parse.quote(ENVIRONMENT, safe="")
    environment_path = f"/repos/{REPOSITORY}/environments/{encoded_environment}"
    _, before = api_request("GET", environment_path, token, expected={200})
    if not isinstance(before, dict):
        raise ConfigurationError("GitHub returned a malformed environment object")

    payload = extract_protection_settings(before)
    api_request(
        "PUT",
        environment_path,
        token,
        body=payload,
        expected={200},
    )

    policies_path = f"{environment_path}/deployment-branch-policies"
    _, policies_payload = api_request(
        "GET",
        f"{policies_path}?per_page=100",
        token,
        expected={200},
    )
    policies = (
        policies_payload.get("branch_policies")
        if isinstance(policies_payload, dict)
        else None
    )
    if not isinstance(policies, list):
        raise ConfigurationError("GitHub returned malformed deployment branch policies")

    retained = False
    removed: list[str] = []
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        name = policy.get("name")
        policy_id = policy.get("id")
        if name == ALLOWED_BRANCH:
            retained = True
            continue
        if isinstance(policy_id, int) and not isinstance(policy_id, bool):
            api_request(
                "DELETE",
                f"{policies_path}/{policy_id}",
                token,
                expected={204},
            )
            if isinstance(name, str):
                removed.append(name)
    if not retained:
        api_request(
            "POST",
            policies_path,
            token,
            body={"name": ALLOWED_BRANCH, "type": "branch"},
            expected={200, 201, 303},
        )

    configured_variables: list[str] = []
    for name, value in sorted(SAFE_VARIABLES.items()):
        upsert_environment_variable(token, name, value)
        configured_variables.append(name)

    _, after = api_request("GET", environment_path, token, expected={200})
    if not isinstance(after, dict):
        raise ConfigurationError("GitHub returned a malformed post-update environment")
    if extract_protection_settings(after) != payload:
        raise ConfigurationError("environment reviewer/timer protection was not preserved")
    branch_policy = after.get("deployment_branch_policy")
    if branch_policy != {
        "protected_branches": False,
        "custom_branch_policies": True,
    }:
        raise ConfigurationError("environment custom branch policy was not retained")
    _, final_policies_payload = api_request(
        "GET",
        f"{policies_path}?per_page=100",
        token,
        expected={200},
    )
    final_policies = (
        final_policies_payload.get("branch_policies")
        if isinstance(final_policies_payload, dict)
        else None
    )
    final_names = sorted(
        item.get("name")
        for item in final_policies or []
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    if final_names != [ALLOWED_BRANCH]:
        raise ConfigurationError(
            "environment deployment branch policy is not the exact canonical branch"
        )

    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "environment": ENVIRONMENT,
        "status": "PASS",
        "deployment_branch_policy": final_names,
        "removed_branch_policies": sorted(removed),
        "safe_variables_configured": configured_variables,
        "secret_values_read": False,
        "secret_values_written": False,
        "server_contacted": False,
        "ssh_attempted": False,
        "production_changed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--evidence-output", type=Path)
    return parser.parse_args()


def write_evidence(path: Path | None, evidence: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if not args.apply:
        print("STAGING_READONLY_ENVIRONMENT_CONFIGURATION=DRY_RUN_ONLY")
        return 0
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        write_evidence(
            args.evidence_output,
            {
                "schema_version": 1,
                "repository": REPOSITORY,
                "environment": ENVIRONMENT,
                "status": "BLOCKED",
                "missing_secret": TOKEN_ENV,
                "secret_values_read": False,
                "secret_values_written": False,
                "server_contacted": False,
                "ssh_attempted": False,
                "production_changed": False,
            },
        )
        print(
            f"STAGING_READONLY_ENVIRONMENT_BLOCKER=missing {TOKEN_ENV}",
            file=sys.stderr,
        )
        return 1
    try:
        evidence = configure(token)
    except ConfigurationError as exc:
        evidence = {
            "schema_version": 1,
            "repository": REPOSITORY,
            "environment": ENVIRONMENT,
            "status": "BLOCKED",
            "error": str(exc),
            "secret_values_read": False,
            "secret_values_written": False,
            "server_contacted": False,
            "ssh_attempted": False,
            "production_changed": False,
        }
        write_evidence(args.evidence_output, evidence)
        print(f"STAGING_READONLY_ENVIRONMENT_BLOCKER={exc}", file=sys.stderr)
        return 1
    write_evidence(args.evidence_output, evidence)
    print("STAGING_READONLY_ENVIRONMENT_CONFIGURATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
