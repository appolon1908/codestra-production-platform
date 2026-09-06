#!/usr/bin/env python3
"""Validate sanitized 15-application API and 29-route gateway evidence.

This tool validates results collected by an isolated staging runner. It never sends an
HTTP request, reads a credential, contacts a server, or enables a runtime capability.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "business-api-gateway-certification-policy.v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FORBIDDEN = (
    "UNKNOWN", "PENDING", "NOT_RUN", "NOT_STARTED", "NONE", "TBD", "TODO",
    "REPLACE_ME", "UNVERIFIED", "UNRESOLVED", "LOCAL_ONLY"
)
SECRET_KEYS = (
    "password", "secret_value", "private_key", "access_token", "refresh_token",
    "authorization_value", "cookie_value", "client_secret", "ssh_key", "token_value"
)


class CertificationError(RuntimeError):
    """Malformed or failing certification evidence."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CertificationError(f"cannot parse JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CertificationError(f"JSON root must be an object: {path}")
    return value


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def reject_secret_or_placeholder_values(value: Any) -> None:
    for path, child in walk(value):
        if isinstance(child, str):
            upper = child.upper()
            if any(marker == upper or marker in upper for marker in FORBIDDEN):
                raise CertificationError(f"unresolved value at {path}")
            if "-----BEGIN" in child or upper.startswith("BEARER "):
                raise CertificationError(f"credential-shaped value at {path}")
        if isinstance(child, dict):
            for key, item in child.items():
                normalized = str(key).lower().replace("-", "_")
                if any(fragment in normalized for fragment in SECRET_KEYS):
                    if item not in (None, False, "") and not normalized.endswith("_ref"):
                        raise CertificationError(f"secret value field is prohibited at {path}.{key}")


def require_https(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise CertificationError(f"{path} must be an HTTPS URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CertificationError(f"{path} must be credential-free HTTPS")
    if parsed.fragment:
        raise CertificationError(f"{path} must not contain a fragment")
    return value


def require_nonnegative_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CertificationError(f"{path} must be a non-negative integer")
    return value


def require_positive_int(value: Any, path: str) -> int:
    number = require_nonnegative_int(value, path)
    if number == 0:
        raise CertificationError(f"{path} must be positive")
    return number


def require_pass(value: Any, path: str) -> None:
    if value != "PASS":
        raise CertificationError(f"{path} must be PASS")


def require_reference(value: Any, path: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < 8:
        raise CertificationError(f"{path} must contain an evidence reference")
    if any(marker in value.upper() for marker in FORBIDDEN):
        raise CertificationError(f"{path} is unresolved")
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
        raise CertificationError(f"{path} must not embed credentials")
    return value


def validate_candidate(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "release_id", "platform_source_sha", "endpoint_manifest_sha256"
    }:
        raise CertificationError("candidate fields are incomplete or unexpected")
    release_id = value.get("release_id")
    source_sha = value.get("platform_source_sha")
    manifest_hash = value.get("endpoint_manifest_sha256")
    if not isinstance(release_id, str) or not ID_RE.fullmatch(release_id):
        raise CertificationError("candidate.release_id is invalid")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        raise CertificationError("candidate.platform_source_sha is invalid")
    if not isinstance(manifest_hash, str) or not HEX64_RE.fullmatch(manifest_hash):
        raise CertificationError("candidate.endpoint_manifest_sha256 is invalid")
    return dict(value)


def validate_endpoint(
    value: Any,
    path: str,
    allowed_methods: set[str],
    allowed_statuses: set[int],
    max_latency_ms: int,
) -> dict[str, Any]:
    required = {
        "method", "path", "status_code", "route_exists", "tls_verified",
        "elapsed_ms", "response_size_bytes", "response_body_sha256",
        "sensitive_data_detected", "request_body_sent"
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CertificationError(f"{path} fields are incomplete or unexpected")
    method = value.get("method")
    endpoint_path = value.get("path")
    status = value.get("status_code")
    if method not in allowed_methods:
        raise CertificationError(f"{path}.method is not allowed")
    if not isinstance(endpoint_path, str) or not endpoint_path.startswith("/") or "?" in endpoint_path:
        raise CertificationError(f"{path}.path must be a query-free absolute path")
    if isinstance(status, bool) or not isinstance(status, int) or status not in allowed_statuses:
        raise CertificationError(f"{path}.status_code is not an allowed protected result")
    if status == 404 or status >= 500:
        raise CertificationError(f"{path} returned an unexpected status")
    if value.get("route_exists") is not True:
        raise CertificationError(f"{path}.route_exists must be true")
    if value.get("tls_verified") is not True:
        raise CertificationError(f"{path}.tls_verified must be true")
    elapsed = require_nonnegative_int(value.get("elapsed_ms"), f"{path}.elapsed_ms")
    if elapsed > max_latency_ms:
        raise CertificationError(f"{path}.elapsed_ms exceeds the application budget")
    require_nonnegative_int(value.get("response_size_bytes"), f"{path}.response_size_bytes")
    body_hash = value.get("response_body_sha256")
    if not isinstance(body_hash, str) or not HEX64_RE.fullmatch(body_hash):
        raise CertificationError(f"{path}.response_body_sha256 is invalid")
    if value.get("sensitive_data_detected") is not False:
        raise CertificationError(f"{path}.sensitive_data_detected must be false")
    if value.get("request_body_sent") is not False:
        raise CertificationError(f"{path}.request_body_sent must be false")
    return dict(value)


def validate_application(
    value: Any,
    index: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    path = f"applications[{index}]"
    required = {
        "application", "repository", "expected_source_sha", "expected_image_digest",
        "base_url", "max_latency_ms", "endpoint_results", "authorization",
        "runtime_identity", "openapi_alignment", "gateway_alignment", "evidence_ref"
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CertificationError(f"{path} fields are incomplete or unexpected")
    application = value.get("application")
    repository = value.get("repository")
    expected_sha = value.get("expected_source_sha")
    expected_digest = value.get("expected_image_digest")
    if not isinstance(application, str) or not ID_RE.fullmatch(application):
        raise CertificationError(f"{path}.application is invalid")
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise CertificationError(f"{path}.repository is invalid")
    if not isinstance(expected_sha, str) or not SHA_RE.fullmatch(expected_sha):
        raise CertificationError(f"{path}.expected_source_sha is invalid")
    if not isinstance(expected_digest, str) or not DIGEST_RE.fullmatch(expected_digest):
        raise CertificationError(f"{path}.expected_image_digest is invalid")
    require_https(value.get("base_url"), f"{path}.base_url")
    max_latency = require_positive_int(value.get("max_latency_ms"), f"{path}.max_latency_ms")

    endpoints = value.get("endpoint_results")
    expected_classes = list(policy["required_endpoint_classes"])
    if not isinstance(endpoints, dict) or set(endpoints) != set(expected_classes):
        raise CertificationError(f"{path}.endpoint_results must contain exactly {expected_classes}")
    allowed_methods = set(policy["allowed_methods"])
    allowed_statuses = set(policy["allowed_protected_statuses"])
    normalized_endpoints = {
        name: validate_endpoint(
            endpoints[name], f"{path}.endpoint_results.{name}",
            allowed_methods, allowed_statuses, max_latency
        )
        for name in expected_classes
    }

    authorization = value.get("authorization")
    authorization_fields = {
        "authenticated_positive", "unauthenticated_negative", "wrong_role_negative",
        "wrong_business_negative", "cross_business_leaks"
    }
    if not isinstance(authorization, dict) or set(authorization) != authorization_fields:
        raise CertificationError(f"{path}.authorization is invalid")
    for name in authorization_fields - {"cross_business_leaks"}:
        require_pass(authorization.get(name), f"{path}.authorization.{name}")
    if require_nonnegative_int(
        authorization.get("cross_business_leaks"),
        f"{path}.authorization.cross_business_leaks",
    ) != 0:
        raise CertificationError(f"{path}.authorization.cross_business_leaks must be zero")

    runtime_identity = value.get("runtime_identity")
    identity_fields = {"source_sha_readback", "image_digest_readback"}
    if not isinstance(runtime_identity, dict) or set(runtime_identity) != identity_fields:
        raise CertificationError(f"{path}.runtime_identity is invalid")
    if runtime_identity.get("source_sha_readback") != expected_sha:
        raise CertificationError(f"{path} runtime source SHA does not match the candidate")
    if runtime_identity.get("image_digest_readback") != expected_digest:
        raise CertificationError(f"{path} runtime image digest does not match the candidate")

    openapi = value.get("openapi_alignment")
    openapi_fields = {"status", "source_sha256", "runtime_sha256", "source_path_count", "runtime_path_count"}
    if not isinstance(openapi, dict) or set(openapi) != openapi_fields:
        raise CertificationError(f"{path}.openapi_alignment is invalid")
    require_pass(openapi.get("status"), f"{path}.openapi_alignment.status")
    source_hash = openapi.get("source_sha256")
    runtime_hash = openapi.get("runtime_sha256")
    if not isinstance(source_hash, str) or not HEX64_RE.fullmatch(source_hash):
        raise CertificationError(f"{path}.openapi_alignment.source_sha256 is invalid")
    if runtime_hash != source_hash:
        raise CertificationError(f"{path} source and runtime OpenAPI hashes differ")
    source_count = require_positive_int(openapi.get("source_path_count"), f"{path}.openapi_alignment.source_path_count")
    runtime_count = require_positive_int(openapi.get("runtime_path_count"), f"{path}.openapi_alignment.runtime_path_count")
    if source_count != runtime_count:
        raise CertificationError(f"{path} source and runtime OpenAPI path counts differ")

    gateway = value.get("gateway_alignment")
    if not isinstance(gateway, dict) or set(gateway) != {"status", "route_names"}:
        raise CertificationError(f"{path}.gateway_alignment is invalid")
    require_pass(gateway.get("status"), f"{path}.gateway_alignment.status")
    route_names = gateway.get("route_names")
    if not isinstance(route_names, list) or not route_names:
        raise CertificationError(f"{path}.gateway_alignment.route_names is empty")
    if len(route_names) != len(set(route_names)) or not all(
        isinstance(name, str) and ID_RE.fullmatch(name) for name in route_names
    ):
        raise CertificationError(f"{path}.gateway_alignment.route_names is invalid")
    require_reference(value.get("evidence_ref"), f"{path}.evidence_ref")

    return {
        "application": application,
        "repository": repository,
        "expected_source_sha": expected_sha,
        "expected_image_digest": expected_digest,
        "base_url": value["base_url"],
        "max_latency_ms": max_latency,
        "endpoint_results": normalized_endpoints,
        "authorization": authorization,
        "runtime_identity": runtime_identity,
        "openapi_alignment": openapi,
        "gateway_alignment": gateway,
        "evidence_ref": value["evidence_ref"],
    }


def validate_kong_route(
    value: Any,
    index: int,
    applications: set[str],
    allowed_statuses: set[int],
) -> dict[str, Any]:
    path = f"kong_routes[{index}]"
    required = {
        "name", "application", "method", "path", "status_code", "route_exists",
        "tls_verified", "authentication_boundary", "source_match", "digest_match",
        "elapsed_ms", "latency_limit_ms", "write_effect_observed", "evidence_ref"
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CertificationError(f"{path} fields are incomplete or unexpected")
    name = value.get("name")
    application = value.get("application")
    method = value.get("method")
    route_path = value.get("path")
    status = value.get("status_code")
    if not isinstance(name, str) or not ID_RE.fullmatch(name):
        raise CertificationError(f"{path}.name is invalid")
    if application not in applications:
        raise CertificationError(f"{path}.application is not one of the 15 APIs")
    if method not in {"GET", "HEAD"}:
        raise CertificationError(f"{path}.method must be GET or HEAD")
    if not isinstance(route_path, str) or not route_path.startswith("/") or "?" in route_path:
        raise CertificationError(f"{path}.path is invalid")
    if isinstance(status, bool) or not isinstance(status, int) or status not in allowed_statuses:
        raise CertificationError(f"{path}.status_code is not an allowed protected result")
    if status == 404 or status >= 500:
        raise CertificationError(f"{path} returned an unexpected status")
    for field in ("route_exists", "tls_verified", "source_match", "digest_match"):
        if value.get(field) is not True:
            raise CertificationError(f"{path}.{field} must be true")
    require_pass(value.get("authentication_boundary"), f"{path}.authentication_boundary")
    elapsed = require_nonnegative_int(value.get("elapsed_ms"), f"{path}.elapsed_ms")
    limit = require_positive_int(value.get("latency_limit_ms"), f"{path}.latency_limit_ms")
    if elapsed > limit:
        raise CertificationError(f"{path}.elapsed_ms exceeds its route budget")
    if value.get("write_effect_observed") is not False:
        raise CertificationError(f"{path}.write_effect_observed must be false")
    require_reference(value.get("evidence_ref"), f"{path}.evidence_ref")
    return dict(value)


def validate_summary(value: Any) -> dict[str, int]:
    required = {
        "unexpected_404", "unexpected_5xx", "cross_business_leaks", "calls_delta",
        "emails_delta", "sms_delta", "provider_effects_delta", "business_writes_delta",
        "secrets_in_responses", "secrets_in_logs"
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CertificationError("summary fields are incomplete or unexpected")
    result: dict[str, int] = {}
    for name in sorted(required):
        observed = require_nonnegative_int(value.get(name), f"summary.{name}")
        if observed != 0:
            raise CertificationError(f"summary.{name} must be zero")
        result[name] = 0
    return result


def validate_safety(value: Any) -> dict[str, bool]:
    required = {
        "business_writes", "communications_delivery", "provider_effects",
        "financial_or_trading_mutation"
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CertificationError("safety fields are incomplete or unexpected")
    enabled = sorted(name for name, state in value.items() if state is not False)
    if enabled:
        raise CertificationError(f"safety effects must remain false: {enabled}")
    return {name: False for name in sorted(required)}


def validate(evidence: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    reject_secret_or_placeholder_values(evidence)
    required_root = {"schema_version", "candidate", "applications", "kong_routes", "summary", "safety"}
    if set(evidence) != required_root or evidence.get("schema_version") != 1:
        raise CertificationError("evidence root fields are incomplete or unexpected")
    applications_raw = evidence.get("applications")
    expected_apps = int(policy["expected_business_applications"])
    if not isinstance(applications_raw, list) or len(applications_raw) != expected_apps:
        raise CertificationError(f"applications must contain exactly {expected_apps} entries")
    applications = [
        validate_application(item, index, policy)
        for index, item in enumerate(applications_raw)
    ]
    application_names = [item["application"] for item in applications]
    repositories = [item["repository"] for item in applications]
    if len(application_names) != len(set(application_names)):
        raise CertificationError("application identifiers must be unique")
    if len(repositories) != len(set(repositories)):
        raise CertificationError("business API repositories must be unique")

    routes_raw = evidence.get("kong_routes")
    expected_routes = int(policy["expected_kong_routes"])
    if not isinstance(routes_raw, list) or len(routes_raw) != expected_routes:
        raise CertificationError(f"kong_routes must contain exactly {expected_routes} entries")
    allowed_statuses = set(policy["allowed_protected_statuses"])
    routes = [
        validate_kong_route(item, index, set(application_names), allowed_statuses)
        for index, item in enumerate(routes_raw)
    ]
    route_names = [item["name"] for item in routes]
    route_keys = [(item["application"], item["method"], item["path"]) for item in routes]
    if len(route_names) != len(set(route_names)):
        raise CertificationError("Kong route names must be unique")
    if len(route_keys) != len(set(route_keys)):
        raise CertificationError("Kong application/method/path tuples must be unique")
    referenced = {
        name
        for application in applications
        for name in application["gateway_alignment"]["route_names"]
    }
    if referenced != set(route_names):
        missing = sorted(set(route_names) - referenced)
        unknown = sorted(referenced - set(route_names))
        raise CertificationError(f"application-to-gateway route coverage mismatch; missing={missing}, unknown={unknown}")

    return {
        "schema_version": 1,
        "status": "PASS",
        "candidate": validate_candidate(evidence.get("candidate")),
        "applications": sorted(applications, key=lambda item: item["application"]),
        "kong_routes": sorted(routes, key=lambda item: item["name"]),
        "summary": validate_summary(evidence.get("summary")),
        "safety": validate_safety(evidence.get("safety")),
        "business_apis": f"{len(applications)}/{expected_apps}",
        "gateway_routes": f"{len(routes)}/{expected_routes}",
        "runtime_contacted_by_validator": False,
        "production_changed_by_validator": False,
        "secret_values_recorded": False,
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
    except CertificationError as exc:
        print("BUSINESS_API_GATEWAY_CERTIFICATION=BLOCKED", file=sys.stderr)
        print(f"BLOCKER={exc}", file=sys.stderr)
        return 2
    if args.result_output:
        args.result_output.parent.mkdir(parents=True, exist_ok=True)
        args.result_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("BUSINESS_API_GATEWAY_CERTIFICATION=PASS")
    print(f"BUSINESS_APIS={result['business_apis']}")
    print(f"GATEWAY_ROUTES={result['gateway_routes']}")
    print("UNEXPECTED_404=0")
    print("UNEXPECTED_5XX=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
