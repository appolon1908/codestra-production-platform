#!/usr/bin/env python3
"""Fail-closed manual portfolio release orchestration.

The controller validates a committed candidate, verifies exact repository heads,
contracts and required checks through GitHub, dispatches normalized release-intent
workflows, and invokes the existing infrastructure staging/rollback/canary
authority. It never accepts mutable tags, rebuilds between stages, or missing
evidence as success.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config/manual-production-orchestrator.catalog.v1.json"
TEMPLATE_PATH = ROOT / "config/manual-production-candidate.template.v1.json"

CATALOG_SCHEMA = "codestra.manual-production-orchestrator.catalog.v1"
CANDIDATE_SCHEMA = "codestra.manual-production-candidate.v1"
CONTRACT_SCHEMA = "codestra.production-orchestrator-contract.v1"
INTENT_WORKFLOW = ".github/workflows/manual-release-intent.yml"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$")
IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$")
PHASES = ("plan", "staging", "canary", "production")
CONFIRMATIONS = {
    "plan": "PLAN_PORTFOLIO_RELEASE",
    "staging": "DEPLOY_PORTFOLIO_STAGING",
    "canary": "START_PORTFOLIO_READONLY_CANARY",
    "production": "PROMOTE_PORTFOLIO_TO_100_PERCENT",
}
SAFETY_KEYS = {
    "external_effects_enabled",
    "live_email_delivery",
    "live_sms_delivery",
    "live_pstn_dialing",
    "odoo_write",
    "n8n_external_delivery",
    "live_trading",
    "payment_execution",
}
ZERO40 = "0" * 40
ZERO64 = "0" * 64


class PolicyError(ValueError):
    """Raised when a release policy or external authority fails closed."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"unable to load JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise PolicyError(f"{path} must contain one JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PolicyError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_sha(value: object, name: str, *, allow_zero: bool = False) -> str:
    require(isinstance(value, str) and HEX40.fullmatch(value) is not None, f"{name} must be a lowercase 40-hex SHA")
    if not allow_zero:
        require(value != ZERO40, f"{name} must not be the zero placeholder")
    return value


def require_digest(value: object, name: str, *, allow_zero: bool = False) -> str:
    require(isinstance(value, str) and HEX64.fullmatch(value) is not None, f"{name} must be a lowercase 64-hex digest")
    if not allow_zero:
        require(value != ZERO64, f"{name} must not be the zero placeholder")
    return value


def validate_catalog(catalog: dict[str, Any]) -> None:
    require(catalog.get("schema_version") == CATALOG_SCHEMA, "unexpected catalog schema")
    controller = catalog.get("controller")
    require(isinstance(controller, dict), "catalog controller must be an object")
    require(controller.get("repository") == "appolon1908-hue/codestra-production-platform", "unexpected controller repository")
    require(controller.get("repository_id") == 1314230781, "unexpected controller repository ID")
    require(controller.get("branch") == "release/production-activation", "unexpected controller branch")
    require(controller.get("workflow") == ".github/workflows/manual-one-click-production-orchestrator.yml", "unexpected controller workflow")
    require(catalog.get("contract_path") == ".codestra/production-orchestrator-contract.v1.json", "unexpected contract path")
    require(catalog.get("release_intent_workflow") == INTENT_WORKFLOW, "unexpected release-intent workflow")

    authority = catalog.get("authority_policy")
    require(isinstance(authority, dict), "catalog authority_policy must be an object")
    require(
        authority.get("controller") == "appolon1908-hue/codestra-production-platform",
        "controller authority mismatch",
    )
    require(
        authority.get("infrastructure_runtime") == "appolon1908-hue/Infustruction-repo",
        "infrastructure runtime authority mismatch",
    )
    require(
        authority.get("canonical_middleware") == "appolon1908-hue/Middleware-",
        "canonical Middleware authority mismatch",
    )
    require(
        authority.get("legacy_middleware_rollback_only") == "Codestra-SRL/codestra-middleware",
        "legacy Middleware rollback authority mismatch",
    )

    check_policy = catalog.get("check_policy")
    require(isinstance(check_policy, dict), "catalog check_policy must be an object")
    require(check_policy.get("default_app_id") == 15368, "required check app must remain GitHub Actions")
    require(
        check_policy.get("require_protected_branch_binding") is True,
        "required checks must remain bound by branch protection",
    )

    repositories = catalog.get("repositories")
    require(isinstance(repositories, list) and len(repositories) == 12, "catalog must contain exactly 12 repositories")
    names: list[str] = []
    ids: list[int] = []
    orders: list[int] = []
    for index, record in enumerate(repositories):
        require(isinstance(record, dict), f"catalog repository #{index} must be an object")
        repository = record.get("repository")
        repository_id = record.get("repository_id")
        default_branch = record.get("default_branch")
        order = record.get("order")
        require(isinstance(repository, str) and repository.count("/") == 1, f"invalid repository at index {index}")
        require(isinstance(repository_id, int) and repository_id > 0, f"invalid repository ID for {repository}")
        require(isinstance(default_branch, str) and default_branch, f"invalid default branch for {repository}")
        require(isinstance(order, int) and order > 0, f"invalid order for {repository}")
        require(record.get("required") is True, f"{repository} must remain required")
        names.append(repository)
        ids.append(repository_id)
        orders.append(order)
    require(len(names) == len(set(names)), "catalog repositories must be unique")
    require(len(ids) == len(set(ids)), "catalog repository IDs must be unique")
    require(len(orders) == len(set(orders)), "catalog orders must be unique")
    roles = {record["repository"]: record.get("role") for record in repositories}
    require(
        roles.get(authority["canonical_middleware"]) == "canonical-middleware",
        "canonical Middleware catalog role mismatch",
    )
    require(
        sum(role == "canonical-middleware" for role in roles.values()) == 1,
        "catalog must declare exactly one canonical Middleware authority",
    )
    require(
        authority["legacy_middleware_rollback_only"] not in names,
        "legacy Middleware rollback authority must remain outside the forward catalog",
    )
    require(
        roles.get(authority["infrastructure_runtime"]) == "infrastructure",
        "infrastructure authority catalog role mismatch",
    )
    require(roles.get(authority["controller"]) == "controller", "controller catalog role mismatch")

    safety = catalog.get("safety")
    require(isinstance(safety, dict), "catalog safety must be an object")
    require(safety.get("mutable_tags_authoritative") is False, "mutable tags must not be authoritative")
    require(safety.get("rebuild_between_staging_and_production") is False, "rebuild between stages must remain forbidden")
    require(safety.get("retag_between_staging_and_production") is False, "retag between stages must remain forbidden")
    require(safety.get("maximum_canary_percent") == 1, "canary ceiling must be exactly one percent")
    require(safety.get("external_effects_default") is False, "external effects must default off")


def validate_contract(contract: dict[str, Any], expected: dict[str, Any]) -> None:
    repository = expected["repository"]
    require(contract.get("schema_version") == CONTRACT_SCHEMA, f"{repository}: unexpected contract schema")
    require(contract.get("repository") == repository, f"{repository}: contract repository mismatch")
    require(contract.get("repository_id") == expected["repository_id"], f"{repository}: contract repository ID mismatch")
    require(contract.get("default_branch") == expected["default_branch"], f"{repository}: contract default branch mismatch")
    require(contract.get("role") == expected["role"], f"{repository}: contract role mismatch")
    require(contract.get("release_intent_workflow") == INTENT_WORKFLOW, f"{repository}: unexpected release-intent workflow")

    required_checks = contract.get("required_checks")
    require(isinstance(required_checks, list), f"{repository}: required_checks must be an array")
    if contract.get("deployment_authority") is True:
        require(required_checks, f"{repository}: deployment authority requires at least one exact-head check")
    require(all(isinstance(name, str) and name for name in required_checks), f"{repository}: invalid required check")

    supported = contract.get("supported_phases")
    require(isinstance(supported, list) and supported, f"{repository}: supported_phases must be non-empty")
    require(set(supported) <= set(PHASES), f"{repository}: unsupported phase in contract")
    require("plan" in supported, f"{repository}: plan phase is mandatory")
    if contract.get("deployment_authority") is not True:
        require(supported == ["plan"], f"{repository}: non-deployment authority may only support plan")

    artifacts = contract.get("artifact_policy")
    require(isinstance(artifacts, dict), f"{repository}: artifact_policy must be an object")
    minimum = artifacts.get("minimum_images")
    maximum = artifacts.get("maximum_images")
    require(isinstance(minimum, int) and minimum >= 0, f"{repository}: invalid minimum_images")
    require(isinstance(maximum, int) and maximum >= minimum, f"{repository}: invalid maximum_images")
    require(artifacts.get("require_digest") is True, f"{repository}: immutable image digests are mandatory")
    require(artifacts.get("allow_rebuild_after_staging") is False, f"{repository}: rebuild after staging must be forbidden")
    require(artifacts.get("allow_retag_after_staging") is False, f"{repository}: retag after staging must be forbidden")

    environments = contract.get("environments")
    require(isinstance(environments, dict), f"{repository}: environments must be an object")
    if contract.get("deployment_authority") is True:
        require(environments.get("staging") == "staging-readonly", f"{repository}: staging environment must be staging-readonly")
        require(environments.get("canary") == "production-readonly-canary", f"{repository}: canary environment mismatch")
        require(environments.get("production") == "production", f"{repository}: production environment mismatch")

    safety = contract.get("safety")
    require(isinstance(safety, dict), f"{repository}: safety must be an object")
    for key in (
        "external_effects_default",
        "live_email_delivery",
        "live_sms_delivery",
        "live_pstn_dialing",
        "odoo_write",
        "n8n_external_delivery",
        "live_trading",
        "payment_execution",
    ):
        require(safety.get(key) is False, f"{repository}: {key} must remain false")


def validate_candidate(
    catalog: dict[str, Any],
    candidate: dict[str, Any],
    *,
    phase: str,
    allow_template: bool = False,
) -> None:
    require(phase in PHASES, "unsupported phase")
    require(candidate.get("schema_version") == CANDIDATE_SCHEMA, "unexpected candidate schema")
    template = candidate.get("template")
    require(type(template) is bool, "candidate template must be boolean")
    if not allow_template:
        require(template is False, "template candidate cannot execute")

    release_id = candidate.get("release_id")
    if template and allow_template:
        require(isinstance(release_id, str) and release_id, "template release_id must be present")
    else:
        require(isinstance(release_id, str) and RELEASE_ID.fullmatch(release_id) is not None, "invalid release_id")
    require_sha(candidate.get("controller_sha"), "controller_sha", allow_zero=template and allow_template)
    require_sha(candidate.get("source_lock_sha"), "source_lock_sha", allow_zero=template and allow_template)
    require_digest(candidate.get("runtime_candidate_sha256"), "runtime_candidate_sha256", allow_zero=template and allow_template)

    traffic = candidate.get("traffic")
    require(isinstance(traffic, dict), "traffic must be an object")
    require(traffic.get("canary_percent") == 1, "canary_percent must equal 1")
    require(traffic.get("production_percent") == 100, "production_percent must equal 100")
    require(traffic.get("allowed_canary_methods") == ["GET", "HEAD"], "canary methods must be GET and HEAD only")

    safety = candidate.get("safety")
    require(isinstance(safety, dict), "candidate safety must be an object")
    require(set(safety) == SAFETY_KEYS, "candidate safety controls are incomplete or unexpected")
    for key, value in safety.items():
        require(value is False, f"candidate safety control {key} must be false")

    catalog_by_repo = {item["repository"]: item for item in catalog["repositories"]}
    components = candidate.get("components")
    require(isinstance(components, list) and len(components) == len(catalog_by_repo), "candidate component coverage mismatch")
    candidate_by_repo: dict[str, dict[str, Any]] = {}
    for record in components:
        require(isinstance(record, dict), "candidate component must be an object")
        repository = record.get("repository")
        require(repository in catalog_by_repo, f"unexpected candidate repository: {repository}")
        require(repository not in candidate_by_repo, f"duplicate candidate repository: {repository}")
        require(record.get("enabled") is True, f"{repository}: required component cannot be disabled")
        require_sha(record.get("source_sha"), f"{repository}.source_sha", allow_zero=template and allow_template)
        require_digest(record.get("contract_sha256"), f"{repository}.contract_sha256", allow_zero=template and allow_template)
        images = record.get("images")
        previous = record.get("previous_images")
        require(isinstance(images, list) and isinstance(previous, list), f"{repository}: images must be arrays")
        require(all(isinstance(item, str) and IMAGE.fullmatch(item) for item in images), f"{repository}: invalid immutable image reference")
        require(all(isinstance(item, str) and IMAGE.fullmatch(item) for item in previous), f"{repository}: invalid rollback image reference")
        require(len(images) == len(set(images)), f"{repository}: duplicate candidate image")
        require(len(previous) == len(set(previous)), f"{repository}: duplicate rollback image")
        if not template:
            require(len(previous) == len(images), f"{repository}: rollback image count mismatch")
            require(set(images).isdisjoint(previous), f"{repository}: rollback images must differ from candidate images")
            require(
                sorted(item.split("@sha256:", 1)[0] for item in images)
                == sorted(item.split("@sha256:", 1)[0] for item in previous),
                f"{repository}: rollback images must cover the same immutable image names",
            )
        candidate_by_repo[repository] = record
    require(set(candidate_by_repo) == set(catalog_by_repo), "candidate must cover the exact catalog repository set")
    controller_repository = catalog["authority_policy"]["controller"]
    require(
        candidate_by_repo[controller_repository]["source_sha"] == candidate["controller_sha"],
        "controller component source_sha must equal the reviewed controller policy base",
    )


class NoGitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PolicyError("GitHub API redirects are forbidden")


class GitHub:
    def __init__(self, token: str):
        require(bool(token), "CODESTRA_ORCHESTRATOR_TOKEN is required")
        self.token = token
        self.base = "https://api.github.com"

    @staticmethod
    def _open(request, timeout):
        return urllib.request.build_opener(NoGitHubRedirect()).open(request, timeout=timeout)

    def _request_page(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        allow_not_found: bool = False,
    ) -> tuple[Any, str | None]:
        url = path if path.startswith("https://") else self.base + path
        parsed = urllib.parse.urlsplit(url)
        require(
            parsed.scheme == "https" and parsed.netloc == "api.github.com"
            and not parsed.fragment and not any(ord(c) <= 32 for c in url),
            "GitHub API URL must remain on the trusted origin",
        )
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "codestra-manual-production-orchestrator/1",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._open(request, timeout=60) as response:
                content = response.read()
                next_link = self._next_link(response.headers.get("Link", ""))
                if not content:
                    return None, next_link
                return json.loads(content), next_link
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            if allow_not_found and error.code == 404:
                return None, None
            raise PolicyError(f"GitHub API {method} {path} failed with HTTP {error.code}: {body[:500]}") from error
        except urllib.error.URLError as error:
            raise PolicyError(f"GitHub API {method} {path} failed: {error}") from error

    @staticmethod
    def _next_link(header: str) -> str | None:
        for item in header.split(","):
            match = re.fullmatch(r'\s*<([^>]+)>;\s*rel="next"\s*', item)
            if match is not None:
                return match.group(1)
        return None

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        allow_not_found: bool = False,
    ) -> Any:
        value, _ = self._request_page(
            method,
            path,
            payload,
            allow_not_found=allow_not_found,
        )
        return value

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def get_optional(self, path: str) -> Any:
        return self.request("GET", path, allow_not_found=True)

    def get_paginated(self, path: str, *, items_key: str | None = None) -> list[Any]:
        items: list[Any] = []
        next_path: str | None = path
        visited: set[str] = set()
        while next_path is not None:
            require(next_path not in visited, "GitHub API pagination loop detected")
            require(len(visited) < 100, "GitHub API pagination limit exceeded")
            visited.add(next_path)
            page, next_path = self._request_page("GET", next_path)
            if items_key is not None:
                require(isinstance(page, dict), f"GitHub API paginated response is not an object: {path}")
                page = page.get(items_key)
            require(isinstance(page, list), f"GitHub API paginated response is not a list: {path}")
            items.extend(page)
        return items

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("POST", path, payload)


def latest_check_conclusions(checks: list[dict[str, Any]]) -> dict[tuple[str, int], str | None]:
    ordered = sorted(checks, key=lambda item: item.get("completed_at") or item.get("started_at") or "")
    result: dict[tuple[str, int], str | None] = {}
    for item in ordered:
        name = item.get("name")
        app = item.get("app")
        app_id = app.get("id") if isinstance(app, dict) else None
        if isinstance(name, str) and isinstance(app_id, int):
            result[(name, app_id)] = item.get("conclusion")
    return result


def required_check_bindings(
    github: GitHub,
    repository: str,
    branch_name: str,
    expected_app_id: int,
) -> tuple[set[str], dict[str, int]]:
    """Resolve app-bound checks from classic protection and effective rulesets."""

    required: set[str] = set()
    bindings: dict[str, int] = {}

    def add_binding(name: object, app_id: object, authority: str) -> None:
        require(isinstance(name, str) and name, f"{repository}: invalid required check context from {authority}")
        required.add(name)
        if app_id is None:
            return
        require(isinstance(app_id, int), f"{repository}: invalid app binding for required check {name}")
        prior = bindings.get(name)
        require(
            prior is None or prior == app_id,
            f"{repository}: conflicting app bindings for required check {name}",
        )
        require(
            app_id == expected_app_id,
            f"{repository}: required check {name} is bound to the wrong app",
        )
        bindings[name] = app_id

    classic = github.get_optional(
        f"/repos/{repository}/branches/{branch_name}/protection/required_status_checks"
    )
    if classic is not None:
        require(isinstance(classic, dict), f"{repository}: invalid classic required-status policy")
        contexts = classic.get("contexts", [])
        checks = classic.get("checks", [])
        require(isinstance(contexts, list), f"{repository}: invalid branch-protection context list")
        require(isinstance(checks, list), f"{repository}: invalid branch-protection check list")
        for name in contexts:
            add_binding(name, None, "classic branch protection")
        for item in checks:
            require(isinstance(item, dict), f"{repository}: invalid branch-protection check binding")
            add_binding(item.get("context"), item.get("app_id"), "classic branch protection")

    effective_rules = github.get_paginated(
        f"/repos/{repository}/rules/branches/{branch_name}?per_page=100"
    )
    for rule in effective_rules:
        require(isinstance(rule, dict), f"{repository}: invalid effective branch rule")
        if rule.get("type") != "required_status_checks":
            continue
        parameters = rule.get("parameters")
        require(isinstance(parameters, dict), f"{repository}: invalid ruleset status policy")
        checks = parameters.get("required_status_checks")
        require(isinstance(checks, list), f"{repository}: invalid ruleset required-check list")
        for item in checks:
            require(isinstance(item, dict), f"{repository}: invalid ruleset check binding")
            add_binding(item.get("context"), item.get("integration_id"), "effective ruleset")

    return required, bindings


def fetch_contract(github: GitHub, repository: str, source_sha: str, path: str) -> tuple[dict[str, Any], str]:
    encoded_path = urllib.parse.quote(path, safe="/")
    response = github.get(f"/repos/{repository}/contents/{encoded_path}?ref={source_sha}")
    require(isinstance(response, dict) and response.get("encoding") == "base64", f"{repository}: contract content unavailable")
    try:
        content = base64.b64decode(response["content"], validate=False)
        contract = json.loads(content)
    except (KeyError, ValueError, json.JSONDecodeError) as error:
        raise PolicyError(f"{repository}: invalid contract content: {error}") from error
    require(isinstance(contract, dict), f"{repository}: contract must be a JSON object")
    return contract, sha256_bytes(content)


def verify_github(
    catalog: dict[str, Any],
    candidate: dict[str, Any],
    *,
    phase: str,
    candidate_file_sha256: str,
    output: Path,
) -> dict[str, Any]:
    require_digest(candidate_file_sha256, "candidate_file_sha256")
    github = GitHub(os.environ.get("CODESTRA_ORCHESTRATOR_TOKEN", ""))
    candidate_by_repo = {item["repository"]: item for item in candidate["components"]}
    evidence: dict[str, Any] = {
        "schema_version": "codestra.manual-production-preflight.v1",
        "release_id": candidate["release_id"],
        "phase": phase,
        "candidate_sha256": candidate_file_sha256,
        "status": "PASS",
        "repositories": [],
        "secret_values_recorded": False,
        "runtime_contacted": False,
        "production_changed": False,
    }
    controller_repository = catalog["authority_policy"]["controller"]
    expected_check_app_id = catalog["check_policy"]["default_app_id"]
    for expected in sorted(catalog["repositories"], key=lambda item: item["order"]):
        repository = expected["repository"]
        candidate_record = candidate_by_repo[repository]
        metadata = github.get(f"/repos/{repository}")
        require(metadata.get("id") == expected["repository_id"], f"{repository}: stable repository ID mismatch")
        require(metadata.get("archived") is False and metadata.get("disabled") is False, f"{repository}: repository unavailable")
        require(metadata.get("default_branch") == expected["default_branch"], f"{repository}: default branch drift")

        branch_name = urllib.parse.quote(expected["default_branch"], safe="")
        branch = github.get(f"/repos/{repository}/branches/{branch_name}")
        require(branch.get("protected") is True, f"{repository}: default branch is not protected")
        observed_sha = branch.get("commit", {}).get("sha")
        require_sha(observed_sha, f"{repository}: protected branch head")
        if repository == controller_repository:
            require(
                candidate_record["source_sha"] == candidate["controller_sha"],
                f"{repository}: controller policy-base binding mismatch",
            )
            comparison = github.get(
                f"/repos/{repository}/compare/{candidate_record['source_sha']}...{observed_sha}"
            )
            require(
                comparison.get("status") in {"ahead", "identical"},
                f"{repository}: controller policy base is not an ancestor of the protected workflow head",
            )
            contract_ref = observed_sha
            validation_sha = observed_sha
        else:
            require(
                observed_sha == candidate_record["source_sha"],
                f"{repository}: candidate SHA is not the exact protected branch head",
            )
            contract_ref = candidate_record["source_sha"]
            validation_sha = candidate_record["source_sha"]

        contract, contract_sha = fetch_contract(
            github,
            repository,
            contract_ref,
            catalog["contract_path"],
        )
        require(contract_sha == candidate_record["contract_sha256"], f"{repository}: contract SHA-256 mismatch")
        validate_contract(contract, expected)

        artifacts = contract["artifact_policy"]
        image_count = len(candidate_record["images"])
        require(
            artifacts["minimum_images"] <= image_count <= artifacts["maximum_images"],
            f"{repository}: candidate image count violates contract",
        )
        require(len(candidate_record["previous_images"]) == image_count, f"{repository}: rollback image count mismatch")

        branch_required, required_apps = required_check_bindings(
            github,
            repository,
            branch_name,
            expected_check_app_id,
        )
        contract_checks = set(contract["required_checks"])
        required_checks = sorted(branch_required | contract_checks)
        if catalog["check_policy"]["require_protected_branch_binding"] is True:
            unbound = sorted(set(required_checks) - set(required_apps))
            require(not unbound, f"{repository}: contract checks are not bound by branch protection: {unbound}")
        require(required_checks, f"{repository}: protected branch has no required exact-head checks")
        check_runs = github.get_paginated(
            f"/repos/{repository}/commits/{validation_sha}/check-runs?per_page=100",
            items_key="check_runs",
        )
        require(all(isinstance(check, dict) for check in check_runs), f"{repository}: invalid check run")
        checks = latest_check_conclusions(check_runs)
        missing = [
            name
            for name in required_checks
            if checks.get((name, required_apps[name])) != "success"
        ]
        require(not missing, f"{repository}: required exact-head checks not successful: {missing}")

        commit = github.get(f"/repos/{repository}/commits/{validation_sha}")
        if contract.get("require_verified_commit") is True:
            require(
                commit.get("commit", {}).get("verification", {}).get("verified") is True,
                f"{repository}: exact source commit is not GitHub-verified",
            )

        supported = phase in contract["supported_phases"]
        if contract.get("deployment_authority") is True:
            require(supported, f"{repository}: phase {phase} is not supported")
        evidence["repositories"].append(
            {
                "repository": repository,
                "repository_id": expected["repository_id"],
                "role": expected["role"],
                "source_sha": candidate_record["source_sha"],
                "validated_head_sha": validation_sha,
                "contract_sha256": contract_sha,
                "required_checks": required_checks,
                "required_check_apps": {
                    name: required_apps[name]
                    for name in required_checks
                },
                "phase_supported": supported,
                "deployment_authority": contract.get("deployment_authority") is True,
                "images": candidate_record["images"],
                "previous_images": candidate_record["previous_images"],
                "status": "PASS",
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def confirmation_for_intent(phase: str) -> str:
    return {
        "plan": "PLAN_RELEASE_INTENT",
        "staging": "APPROVE_STAGING_INTENT",
        "canary": "APPROVE_CANARY_INTENT",
        "production": "APPROVE_PRODUCTION_INTENT",
    }[phase]


def wait_for_dispatch_run(
    github: GitHub,
    repository: str,
    workflow: str,
    branch: str,
    source_sha: str,
    started_after: dt.datetime,
    timeout_seconds: int,
) -> dict[str, Any]:
    encoded_workflow = urllib.parse.quote(workflow, safe="")
    deadline = time.monotonic() + timeout_seconds
    selected: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        runs = github.get(
            f"/repos/{repository}/actions/workflows/{encoded_workflow}/runs"
            f"?event=workflow_dispatch&branch={urllib.parse.quote(branch, safe='')}&per_page=20"
        ).get("workflow_runs", [])
        for run in runs:
            created = run.get("created_at")
            if not isinstance(created, str):
                continue
            created_at = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created_at >= started_after and run.get("head_sha") == source_sha:
                selected = run
                break
        if selected:
            break
        time.sleep(5)
    require(selected is not None, f"{repository}: dispatched workflow run was not observed")

    run_id = selected["id"]
    while time.monotonic() < deadline:
        run = github.get(f"/repos/{repository}/actions/runs/{run_id}")
        if run.get("status") == "completed":
            require(run.get("conclusion") == "success", f"{repository}: release-intent run {run_id} concluded {run.get('conclusion')}")
            return run
        time.sleep(10)
    raise PolicyError(f"{repository}: release-intent run {run_id} timed out")


def dispatch_intents(
    catalog: dict[str, Any],
    candidate: dict[str, Any],
    *,
    phase: str,
    candidate_file_sha256: str,
    prior_evidence_sha256: str,
    output: Path,
) -> dict[str, Any]:
    github = GitHub(os.environ.get("CODESTRA_ORCHESTRATOR_TOKEN", ""))
    candidate_by_repo = {item["repository"]: item for item in candidate["components"]}
    timeout_seconds = int(os.environ.get("CODESTRA_ORCHESTRATOR_TIMEOUT_SECONDS", "7200"))
    evidence: dict[str, Any] = {
        "schema_version": "codestra.manual-release-intents.v1",
        "release_id": candidate["release_id"],
        "phase": phase,
        "candidate_file_sha256": candidate_file_sha256,
        "prior_evidence_sha256": prior_evidence_sha256,
        "status": "PASS",
        "runs": [],
        "runtime_contacted_by_controller": False,
        "production_changed_by_controller": False,
    }
    controller_repository = catalog["authority_policy"]["controller"]
    for expected in sorted(catalog["repositories"], key=lambda item: item["order"]):
        repository = expected["repository"]
        record = candidate_by_repo[repository]
        intent_source_sha = record["source_sha"]
        if repository == controller_repository:
            branch_name = urllib.parse.quote(expected["default_branch"], safe="")
            branch = github.get(f"/repos/{repository}/branches/{branch_name}")
            require(branch.get("protected") is True, f"{repository}: controller branch is not protected")
            intent_source_sha = require_sha(
                branch.get("commit", {}).get("sha"),
                f"{repository}: controller intent head",
            )
            workflow_sha = require_sha(
                os.environ.get("GITHUB_SHA", ""),
                f"{repository}: controller workflow SHA",
            )
            require(
                intent_source_sha == workflow_sha,
                f"{repository}: protected controller head moved after candidate validation",
            )
            comparison = github.get(
                f"/repos/{repository}/compare/{record['source_sha']}...{intent_source_sha}"
            )
            require(
                comparison.get("status") in {"ahead", "identical"},
                f"{repository}: controller policy base is not an ancestor of the intent head",
            )
        contract, _ = fetch_contract(
            github,
            repository,
            intent_source_sha,
            catalog["contract_path"],
        )
        if contract.get("deployment_authority") is not True and phase != "plan":
            evidence["runs"].append(
                {
                    "repository": repository,
                    "source_sha": record["source_sha"],
                    "status": "VERIFIED_ONLY",
                    "reason": "contract is not a deployment authority",
                }
            )
            continue
        require(phase in contract["supported_phases"], f"{repository}: {phase} intent not supported")
        started_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2)
        payload = {
            "ref": expected["default_branch"],
            "inputs": {
                "phase": phase,
                "source_sha": intent_source_sha,
                "release_id": candidate["release_id"],
                "candidate_sha256": candidate_file_sha256,
                "images_json": json.dumps(record["images"], separators=(",", ":")),
                "previous_images_json": json.dumps(record["previous_images"], separators=(",", ":")),
                "prior_evidence_sha256": prior_evidence_sha256,
                "confirmation": confirmation_for_intent(phase),
            },
        }
        encoded_workflow = urllib.parse.quote(INTENT_WORKFLOW, safe="")
        github.post(f"/repos/{repository}/actions/workflows/{encoded_workflow}/dispatches", payload)
        run = wait_for_dispatch_run(
            github,
            repository,
            INTENT_WORKFLOW,
            expected["default_branch"],
            intent_source_sha,
            started_after,
            timeout_seconds,
        )
        artifacts = github.get(f"/repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100").get("artifacts", [])
        prefix = f"codestra-release-intent-{phase}-{intent_source_sha}"
        matches = [artifact for artifact in artifacts if artifact.get("name") == prefix and not artifact.get("expired")]
        require(len(matches) == 1, f"{repository}: normalized release-intent artifact missing or ambiguous")
        evidence["runs"].append(
            {
                "repository": repository,
                "source_sha": intent_source_sha,
                "controller_policy_base_sha": (
                    record["source_sha"] if repository == controller_repository else None
                ),
                "run_id": run["id"],
                "run_attempt": run.get("run_attempt"),
                "artifact_id": matches[0]["id"],
                "artifact_name": matches[0]["name"],
                "artifact_digest": matches[0].get("digest"),
                "status": "PASS",
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def dispatch_infrastructure(
    catalog: dict[str, Any],
    candidate: dict[str, Any],
    *,
    mode: str,
    staging_run_id: str,
    rollback_run_id: str,
    output: Path,
) -> dict[str, Any]:
    github = GitHub(os.environ.get("CODESTRA_ORCHESTRATOR_TOKEN", ""))
    repository = "appolon1908-hue/Infustruction-repo"
    workflow = ".github/workflows/staging-readonly-certification.yml"
    source_sha = next(
        item["source_sha"]
        for item in candidate["components"]
        if item["repository"] == repository
    )
    inputs: dict[str, str] = {
        "mode": mode,
        "confirm_candidate_id": candidate["release_id"],
        "confirm_source_lock_sha": candidate["source_lock_sha"],
        "confirm_candidate_sha256": candidate["runtime_candidate_sha256"],
        "staging_evidence_run_id": staging_run_id,
        "rollback_evidence_run_id": rollback_run_id,
        "canary_percent": "1",
    }
    if mode == "rollback-rehearsal":
        require(staging_run_id.isdigit(), "staging run ID is required for rollback rehearsal")
    if mode == "production-readonly-canary":
        require(staging_run_id.isdigit(), "staging run ID is required for canary")
        require(rollback_run_id.isdigit(), "rollback run ID is required for canary")

    started_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2)
    github.post(
        f"/repos/{repository}/actions/workflows/{urllib.parse.quote(workflow, safe='')}/dispatches",
        {"ref": "main", "inputs": inputs},
    )
    run = wait_for_dispatch_run(
        github,
        repository,
        workflow,
        "main",
        source_sha,
        started_after,
        int(os.environ.get("CODESTRA_ORCHESTRATOR_TIMEOUT_SECONDS", "10800")),
    )
    artifact_name = {
        "staging": f"codestra-staging-readonly-{candidate['release_id']}",
        "rollback-rehearsal": f"codestra-rollback-rehearsal-{candidate['release_id']}",
        "production-readonly-canary": f"codestra-production-readonly-canary-{candidate['release_id']}",
    }[mode]
    artifacts = github.get(f"/repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100").get("artifacts", [])
    matches = [artifact for artifact in artifacts if artifact.get("name") == artifact_name and not artifact.get("expired")]
    require(len(matches) == 1, f"infrastructure {mode}: expected evidence artifact is missing or ambiguous")
    evidence = {
        "schema_version": "codestra.infrastructure-dispatch-evidence.v1",
        "repository": repository,
        "source_sha": source_sha,
        "release_id": candidate["release_id"],
        "mode": mode,
        "run_id": run["id"],
        "run_attempt": run.get("run_attempt"),
        "artifact_id": matches[0]["id"],
        "artifact_name": artifact_name,
        "artifact_digest": matches[0].get("digest"),
        "status": "PASS",
        "production_changed": mode == "production-readonly-canary",
        "maximum_traffic_percent": 1 if mode == "production-readonly-canary" else 0,
        "external_effects_enabled": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def dispatch_production(
    candidate: dict[str, Any],
    *,
    staging_run_id: str,
    rollback_run_id: str,
    canary_run_id: str,
    observation_evidence_sha256: str,
    output: Path,
) -> dict[str, Any]:
    require(staging_run_id.isdigit(), "staging run ID is required")
    require(rollback_run_id.isdigit(), "rollback run ID is required")
    require(canary_run_id.isdigit(), "canary run ID is required")
    require_digest(observation_evidence_sha256, "observation_evidence_sha256")
    github = GitHub(os.environ.get("CODESTRA_ORCHESTRATOR_TOKEN", ""))
    repository = "appolon1908-hue/Infustruction-repo"
    workflow = ".github/workflows/production-traffic-promotion.yml"
    source_sha = next(
        item["source_sha"]
        for item in candidate["components"]
        if item["repository"] == repository
    )
    inputs = {
        "confirm_candidate_id": candidate["release_id"],
        "confirm_source_lock_sha": candidate["source_lock_sha"],
        "confirm_candidate_sha256": candidate["runtime_candidate_sha256"],
        "staging_evidence_run_id": staging_run_id,
        "rollback_evidence_run_id": rollback_run_id,
        "canary_evidence_run_id": canary_run_id,
        "observation_evidence_sha256": observation_evidence_sha256,
        "production_percent": "100",
        "confirmation": f"PROMOTE {candidate['release_id']} TO 100 PERCENT",
    }
    started_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2)
    github.post(
        f"/repos/{repository}/actions/workflows/{urllib.parse.quote(workflow, safe='')}/dispatches",
        {"ref": "main", "inputs": inputs},
    )
    run = wait_for_dispatch_run(
        github,
        repository,
        workflow,
        "main",
        source_sha,
        started_after,
        int(os.environ.get("CODESTRA_ORCHESTRATOR_TIMEOUT_SECONDS", "10800")),
    )
    artifact_name = f"codestra-production-traffic-{candidate['release_id']}"
    artifacts = github.get(f"/repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100").get("artifacts", [])
    matches = [artifact for artifact in artifacts if artifact.get("name") == artifact_name and not artifact.get("expired")]
    require(len(matches) == 1, "production traffic evidence artifact is missing or ambiguous")
    evidence = {
        "schema_version": "codestra.production-traffic-dispatch-evidence.v1",
        "repository": repository,
        "source_sha": source_sha,
        "release_id": candidate["release_id"],
        "run_id": run["id"],
        "run_attempt": run.get("run_attempt"),
        "artifact_id": matches[0]["id"],
        "artifact_name": artifact_name,
        "artifact_digest": matches[0].get("digest"),
        "status": "PASS",
        "traffic_percent": 100,
        "external_effects_enabled": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def command_validate(arguments: argparse.Namespace) -> int:
    catalog = load_json(Path(arguments.catalog))
    candidate = load_json(Path(arguments.candidate))
    validate_catalog(catalog)
    validate_candidate(catalog, candidate, phase=arguments.phase, allow_template=arguments.allow_template)
    print("manual production orchestrator policy: PASS")
    return 0


def command_github_preflight(arguments: argparse.Namespace) -> int:
    catalog = load_json(Path(arguments.catalog))
    candidate = load_json(Path(arguments.candidate))
    validate_catalog(catalog)
    validate_candidate(catalog, candidate, phase=arguments.phase)
    verify_github(
        catalog,
        candidate,
        phase=arguments.phase,
        candidate_file_sha256=sha256_bytes(Path(arguments.candidate).read_bytes()),
        output=Path(arguments.output),
    )
    print(f"manual production GitHub preflight: PASS: {arguments.output}")
    return 0


def command_dispatch_intents(arguments: argparse.Namespace) -> int:
    catalog = load_json(Path(arguments.catalog))
    candidate_path = Path(arguments.candidate)
    candidate = load_json(candidate_path)
    validate_catalog(catalog)
    validate_candidate(catalog, candidate, phase=arguments.phase)
    actual = sha256_bytes(candidate_path.read_bytes())
    require(actual == arguments.candidate_sha256, "candidate file SHA-256 mismatch")
    dispatch_intents(
        catalog,
        candidate,
        phase=arguments.phase,
        candidate_file_sha256=actual,
        prior_evidence_sha256=arguments.prior_evidence_sha256,
        output=Path(arguments.output),
    )
    print(f"manual release intents: PASS: {arguments.output}")
    return 0


def command_dispatch_infrastructure(arguments: argparse.Namespace) -> int:
    catalog = load_json(Path(arguments.catalog))
    candidate = load_json(Path(arguments.candidate))
    validate_catalog(catalog)
    validate_candidate(catalog, candidate, phase="canary" if arguments.mode == "production-readonly-canary" else "staging")
    dispatch_infrastructure(
        catalog,
        candidate,
        mode=arguments.mode,
        staging_run_id=arguments.staging_run_id,
        rollback_run_id=arguments.rollback_run_id,
        output=Path(arguments.output),
    )
    print(f"infrastructure dispatch: PASS: {arguments.output}")
    return 0


def command_dispatch_production(arguments: argparse.Namespace) -> int:
    catalog = load_json(Path(arguments.catalog))
    candidate = load_json(Path(arguments.candidate))
    validate_catalog(catalog)
    validate_candidate(catalog, candidate, phase="production")
    dispatch_production(
        candidate,
        staging_run_id=arguments.staging_run_id,
        rollback_run_id=arguments.rollback_run_id,
        canary_run_id=arguments.canary_run_id,
        observation_evidence_sha256=arguments.observation_evidence_sha256,
        output=Path(arguments.output),
    )
    print(f"production dispatch: PASS: {arguments.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--catalog", default=str(CATALOG_PATH))
    validate.add_argument("--candidate", default=str(TEMPLATE_PATH))
    validate.add_argument("--phase", choices=PHASES, default="plan")
    validate.add_argument("--allow-template", action="store_true")
    validate.set_defaults(function=command_validate)

    preflight = subparsers.add_parser("github-preflight")
    preflight.add_argument("--catalog", default=str(CATALOG_PATH))
    preflight.add_argument("--candidate", required=True)
    preflight.add_argument("--phase", choices=PHASES, required=True)
    preflight.add_argument("--output", required=True)
    preflight.set_defaults(function=command_github_preflight)

    intents = subparsers.add_parser("dispatch-intents")
    intents.add_argument("--catalog", default=str(CATALOG_PATH))
    intents.add_argument("--candidate", required=True)
    intents.add_argument("--phase", choices=PHASES, required=True)
    intents.add_argument("--candidate-sha256", required=True)
    intents.add_argument("--prior-evidence-sha256", default=ZERO64)
    intents.add_argument("--output", required=True)
    intents.set_defaults(function=command_dispatch_intents)

    infrastructure = subparsers.add_parser("dispatch-infrastructure")
    infrastructure.add_argument("--catalog", default=str(CATALOG_PATH))
    infrastructure.add_argument("--candidate", required=True)
    infrastructure.add_argument(
        "--mode",
        choices=("staging", "rollback-rehearsal", "production-readonly-canary"),
        required=True,
    )
    infrastructure.add_argument("--staging-run-id", default="")
    infrastructure.add_argument("--rollback-run-id", default="")
    infrastructure.add_argument("--output", required=True)
    infrastructure.set_defaults(function=command_dispatch_infrastructure)

    production = subparsers.add_parser("dispatch-production")
    production.add_argument("--catalog", default=str(CATALOG_PATH))
    production.add_argument("--candidate", required=True)
    production.add_argument("--staging-run-id", required=True)
    production.add_argument("--rollback-run-id", required=True)
    production.add_argument("--canary-run-id", required=True)
    production.add_argument("--observation-evidence-sha256", required=True)
    production.add_argument("--output", required=True)
    production.set_defaults(function=command_dispatch_production)
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    try:
        return arguments.function(arguments)
    except PolicyError as error:
        print(f"manual production orchestrator: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
