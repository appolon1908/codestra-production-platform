#!/usr/bin/env python3
"""Materialize a staging-readonly endpoint manifest from verified authorities.

The tool is intentionally unable to make an incomplete source lock or runtime matrix
pass. It imports the production evidence verifier, requires zero findings, derives the
64 component identities, validates the operator-supplied non-secret target catalogue,
and writes one deterministic JSON manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "tools" / "verify_production_certification_evidence.py"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FORBIDDEN_MARKERS = (
    "REPLACE_", "UNKNOWN", "PENDING", "NOT_RUN", "NOT_STARTED", "NONE",
    "TBD", "TODO", "UNVERIFIED", "UNRESOLVED", "LOCAL_ONLY"
)
SENSITIVE_KEYS = (
    "password", "secret_value", "private_key", "access_token", "refresh_token",
    "authorization", "cookie", "client_secret_value", "ssh_key"
)
EXPECTED_ENDPOINTS = ("health", "readiness", "version", "capabilities", "openapi")
ALLOWED_AUTH = {"public-health", "bearer", "oidc", "mtls", "bearer-or-mtls"}
ALLOWED_METHODS = {"GET", "HEAD"}
DENIED_METHODS = ["POST", "PUT", "PATCH", "DELETE", "CONNECT", "TRACE"]


class ManifestError(RuntimeError):
    """Fail-closed materialization error."""


def load_module():
    spec = importlib.util.spec_from_file_location("production_evidence_verifier", VERIFIER_PATH)
    if not spec or not spec.loader:
        raise ManifestError("cannot load production evidence verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot parse JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"JSON root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def walk(value: Any, path: str = "$"):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def reject_placeholders_and_secrets(value: Any) -> None:
    for path, child in walk(value):
        if isinstance(child, str):
            upper = child.upper()
            if any(marker in upper for marker in FORBIDDEN_MARKERS):
                raise ManifestError(f"unresolved value at {path}")
            if "-----BEGIN" in child or "BEARER " in upper:
                raise ManifestError(f"credential-shaped value at {path}")
        if isinstance(child, dict):
            for key, item in child.items():
                normalized = str(key).lower().replace("-", "_")
                if any(token in normalized for token in SENSITIVE_KEYS) and item not in (None, False, ""):
                    if not normalized.endswith("_ref"):
                        raise ManifestError(f"secret value field is prohibited at {path}.{key}")


def require_https(url: Any, path: str) -> str:
    if not isinstance(url, str):
        raise ManifestError(f"{path} must be an HTTPS URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ManifestError(f"{path} must be credential-free HTTPS")
    if parsed.fragment:
        raise ManifestError(f"{path} must not contain a fragment")
    return url


def validate_statuses(value: Any, path: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{path} must contain expected status codes")
    statuses: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 200 or item > 499 or item == 404:
            raise ManifestError(f"{path} contains an unsafe status code")
        statuses.append(item)
    if len(statuses) != len(set(statuses)):
        raise ManifestError(f"{path} contains duplicate status codes")
    return sorted(statuses)


def validate_endpoint(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path} must be an endpoint object")
    allowed = {"method", "path", "expected_statuses", "authentication", "write_effect_allowed"}
    if set(value) != allowed:
        raise ManifestError(f"{path} has missing or unexpected fields")
    method = value.get("method")
    endpoint_path = value.get("path")
    authentication = value.get("authentication")
    if method not in ALLOWED_METHODS:
        raise ManifestError(f"{path}.method must be GET or HEAD")
    if not isinstance(endpoint_path, str) or not endpoint_path.startswith("/") or "?" in endpoint_path:
        raise ManifestError(f"{path}.path must be a query-free absolute path")
    if authentication not in ALLOWED_AUTH:
        raise ManifestError(f"{path}.authentication is invalid")
    if value.get("write_effect_allowed") is not False:
        raise ManifestError(f"{path} may not authorize a write effect")
    return {
        "method": method,
        "path": endpoint_path,
        "expected_statuses": validate_statuses(value.get("expected_statuses"), f"{path}.expected_statuses"),
        "authentication": authentication,
        "write_effect_allowed": False,
    }


def validate_business_apis(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 15:
        raise ManifestError("catalog.business_apis must contain exactly 15 entries")
    applications: set[str] = set()
    repositories: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        path = f"catalog.business_apis[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{path} must be an object")
        required = {
            "application", "repository", "source_sha", "image_digest", "base_url",
            *EXPECTED_ENDPOINTS, "runtime_attribution"
        }
        if set(item) != required:
            raise ManifestError(f"{path} has missing or unexpected fields")
        application = item.get("application")
        repository = item.get("repository")
        source_sha = item.get("source_sha")
        digest = item.get("image_digest")
        if not isinstance(application, str) or not ID_RE.fullmatch(application):
            raise ManifestError(f"{path}.application is invalid")
        if application in applications:
            raise ManifestError(f"duplicate application: {application}")
        applications.add(application)
        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
            raise ManifestError(f"{path}.repository is invalid")
        if repository in repositories:
            raise ManifestError(f"duplicate business API repository: {repository}")
        repositories.add(repository)
        if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
            raise ManifestError(f"{path}.source_sha is invalid")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise ManifestError(f"{path}.image_digest is invalid")
        attribution = item.get("runtime_attribution")
        if not isinstance(attribution, dict) or set(attribution) != {"source_sha_field", "image_digest_field"}:
            raise ManifestError(f"{path}.runtime_attribution is invalid")
        if not all(isinstance(attribution[name], str) and attribution[name] for name in attribution):
            raise ManifestError(f"{path}.runtime_attribution fields are required")
        normalized = {
            "application": application,
            "repository": repository,
            "source_sha": source_sha,
            "image_digest": digest,
            "base_url": require_https(item.get("base_url"), f"{path}.base_url"),
            "runtime_attribution": dict(sorted(attribution.items())),
        }
        for name in EXPECTED_ENDPOINTS:
            normalized[name] = validate_endpoint(item.get(name), f"{path}.{name}")
        result.append(normalized)
    return sorted(result, key=lambda item: item["application"])


def validate_routes(value: Any, applications: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 29:
        raise ManifestError("catalog.kong.routes must contain exactly 29 routes")
    names: set[str] = set()
    identities: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        path = f"catalog.kong.routes[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{path} must be an object")
        required = {"name", "application", "method", "path", "expected_statuses", "write_effect_allowed"}
        if set(item) != required:
            raise ManifestError(f"{path} has missing or unexpected fields")
        name = item.get("name")
        application = item.get("application")
        method = item.get("method")
        route_path = item.get("path")
        if not isinstance(name, str) or not ID_RE.fullmatch(name) or name in names:
            raise ManifestError(f"{path}.name is invalid or duplicated")
        names.add(name)
        if application not in applications:
            raise ManifestError(f"{path}.application does not map to one of the 15 APIs")
        if method not in ALLOWED_METHODS:
            raise ManifestError(f"{path}.method must be GET or HEAD")
        if not isinstance(route_path, str) or not route_path.startswith("/") or "?" in route_path:
            raise ManifestError(f"{path}.path must be a query-free absolute path")
        identity = (application, method, route_path)
        if identity in identities:
            raise ManifestError(f"duplicate Kong route identity: {identity}")
        identities.add(identity)
        if item.get("write_effect_allowed") is not False:
            raise ManifestError(f"{path} may not authorize a write effect")
        result.append({
            "name": name,
            "application": application,
            "method": method,
            "path": route_path,
            "expected_statuses": validate_statuses(item.get("expected_statuses"), f"{path}.expected_statuses"),
            "write_effect_allowed": False,
        })
    return sorted(result, key=lambda item: item["name"])


def validate_zero_counters(value: Any) -> dict[str, dict[str, int]]:
    required = {"calls", "emails", "sms", "provider_effects"}
    if not isinstance(value, dict) or set(value) != required:
        raise ManifestError("catalog.counters must contain exactly the four live-effect counters")
    result: dict[str, dict[str, int]] = {}
    for name in sorted(required):
        entry = value[name]
        if not isinstance(entry, dict) or set(entry) != {"baseline", "maximum_delta"}:
            raise ManifestError(f"catalog.counters.{name} is invalid")
        baseline = entry.get("baseline")
        maximum_delta = entry.get("maximum_delta")
        if isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
            raise ManifestError(f"catalog.counters.{name}.baseline is invalid")
        if maximum_delta != 0:
            raise ManifestError(f"catalog.counters.{name}.maximum_delta must be zero")
        result[name] = {"baseline": baseline, "maximum_delta": 0}
    return result


def require_false_safety(value: Any) -> dict[str, bool]:
    required = {
        "LIVE_WRITE", "ODOO_WRITE", "ENABLE_EXTERNAL_DELIVERY", "N8N_DELIVERY_ENABLED",
        "LIVE_EMAIL_DELIVERY", "LIVE_SMS_DELIVERY", "LIVE_PSTN_DIALING",
        "PRODUCTION_DIALING", "CAMPAIGN_ACTIVATION", "PROVIDER_DELIVERY",
        "ADVERTISING_ACTIVATION", "PAYMENT_EXECUTION", "FINANCIAL_TRADING"
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ManifestError("catalog.safety_controls is incomplete")
    enabled = sorted(name for name, state in value.items() if state is not False)
    if enabled:
        raise ManifestError(f"safety controls must remain false: {enabled}")
    return {name: False for name in sorted(required)}


def validate_passthrough_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ManifestError(f"catalog.{name} must be a non-empty object")
    reject_placeholders_and_secrets(value)
    return value


def build_manifest(
    source_lock: Path,
    matrix: Path,
    policy: Path,
    catalog_path: Path,
    release_id: str,
    platform_source_sha: str,
) -> dict[str, Any]:
    if not ID_RE.fullmatch(release_id):
        raise ManifestError("release ID is invalid")
    if not SHA_RE.fullmatch(platform_source_sha):
        raise ManifestError("platform source SHA is invalid")
    verifier = load_module()
    report = verifier.verify(
        source_lock,
        matrix,
        policy,
        verify_github=False,
        require_pass=True,
    )
    if report.status != "PASS" or report.findings:
        raise ManifestError(f"source lock or immutable matrix is blocked by {len(report.findings)} findings")
    if len(report.workload_evidence) != 64:
        raise ManifestError("verified matrix did not produce exactly 64 workload identities")

    catalog = load_json(catalog_path)
    reject_placeholders_and_secrets(catalog)
    allowed_catalog = {
        "schema_version", "previous_candidate", "identity", "business_apis", "kong",
        "database", "counters", "backups", "rollback", "safety_controls"
    }
    if set(catalog) != allowed_catalog or catalog.get("schema_version") != 1:
        raise ManifestError("catalog root fields are incomplete or unexpected")

    business_apis = validate_business_apis(catalog.get("business_apis"))
    applications = {item["application"] for item in business_apis}
    kong = catalog.get("kong")
    if not isinstance(kong, dict) or set(kong) != {"base_url", "route_count", "routes"}:
        raise ManifestError("catalog.kong is invalid")
    if kong.get("route_count") != 29:
        raise ManifestError("Kong route denominator must be 29")
    routes = validate_routes(kong.get("routes"), applications)

    identity = catalog.get("identity")
    if not isinstance(identity, dict) or set(identity) != {"issuer", "discovery_path", "expected_http_status"}:
        raise ManifestError("catalog.identity is invalid")
    if identity.get("discovery_path") != "/.well-known/openid-configuration" or identity.get("expected_http_status") != 200:
        raise ManifestError("catalog.identity discovery contract is invalid")
    issuer = require_https(identity.get("issuer"), "catalog.identity.issuer")
    if "/realms/" not in issuer:
        raise ManifestError("catalog.identity.issuer must be a Keycloak realm issuer")

    previous = catalog.get("previous_candidate")
    if not isinstance(previous, dict) or set(previous) != {"release_id", "components"}:
        raise ManifestError("catalog.previous_candidate is invalid")
    if not isinstance(previous.get("release_id"), str) or not ID_RE.fullmatch(previous["release_id"]):
        raise ManifestError("previous release ID is invalid")
    if previous["release_id"] == release_id:
        raise ManifestError("previous candidate may not equal the current release")
    if not isinstance(previous.get("components"), list) or not previous["components"]:
        raise ManifestError("previous candidate components are required")

    components = []
    for item in sorted(report.workload_evidence, key=lambda entry: str(entry.get("workload"))):
        components.append({
            "workload": item["workload"],
            "repository": item["repository"],
            "source_sha": item["source_sha"],
            "image": item["image"],
            "image_digest": item["image_digest"],
            "signature": item["signature"],
            "sbom": item["sbom"],
            "provenance": item["provenance"],
            "rollback_digest": item["rollback_digest"],
        })

    matrix_sha = sha256_file(matrix)
    manifest = {
        "schema_version": 1,
        "environment": "staging-readonly",
        "candidate": {
            "release_id": release_id,
            "platform_source_sha": platform_source_sha,
            "source_lock_sha256": sha256_file(source_lock),
            "candidate_manifest_sha256": matrix_sha,
            "components": components,
        },
        "previous_candidate": previous,
        "identity": {
            "issuer": issuer,
            "discovery_path": identity["discovery_path"],
            "expected_http_status": 200,
        },
        "business_apis": business_apis,
        "kong": {
            "base_url": require_https(kong.get("base_url"), "catalog.kong.base_url"),
            "route_count": 29,
            "routes": routes,
        },
        "database": validate_passthrough_object(catalog.get("database"), "database"),
        "counters": validate_zero_counters(catalog.get("counters")),
        "backups": validate_passthrough_object(catalog.get("backups"), "backups"),
        "rollback": validate_passthrough_object(catalog.get("rollback"), "rollback"),
        "canary": {
            "maximum_traffic_percent": 1,
            "allowed_methods": ["GET", "HEAD"],
            "denied_methods": DENIED_METHODS,
            "automatic_rollback_required": True,
        },
        "safety_controls": require_false_safety(catalog.get("safety_controls")),
        "credential_policy": {
            "credentials_embedded": False,
            "bearer_credential_ref": "CODESTRA_STAGING_READONLY_BEARER_TOKEN",
            "metrics_credential_ref": "CODESTRA_STAGING_METRICS_BEARER_TOKEN",
        },
    }
    reject_placeholders_and_secrets(manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=ROOT / "config" / "production-certification-evidence-policy.v1.json")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--platform-source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = build_manifest(
            args.source_lock,
            args.matrix,
            args.policy,
            args.catalog,
            args.release_id,
            args.platform_source_sha,
        )
    except (ManifestError, Exception) as exc:
        if not isinstance(exc, ManifestError):
            print(f"STAGING_MANIFEST_ERROR={type(exc).__name__}: {exc}", file=sys.stderr)
        else:
            print(f"STAGING_MANIFEST_ERROR={exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(manifest))
    print("STAGING_READONLY_ENDPOINT_MANIFEST=PASS")
    print(f"MANIFEST_SHA256={sha256_file(args.output)}")
    print("BUSINESS_APIS=15/15")
    print("KONG_ROUTES=29/29")
    print("WORKLOADS=64/64")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
