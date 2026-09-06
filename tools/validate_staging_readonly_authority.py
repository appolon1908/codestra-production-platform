#!/usr/bin/env python3
"""Validate the protected Codestra staging-readonly execution boundary.

The validator has two modes:

* ``policy`` verifies that the committed authority accurately represents the
  current fail-closed state and that its endpoint-manifest template is safe.
* ``environment`` verifies only secret/variable presence, a materialized
  endpoint manifest, and all source/infrastructure entry gates. Secret values
  are never printed or written to evidence.

No mode deploys, connects to SSH, reads a production secret value, or changes a
runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHORITY = ROOT / "config" / "staging-readonly-authority.v1.json"
DEFAULT_TEMPLATE = (
    ROOT / "config" / "staging-readonly-endpoint-manifest.template.v1.json"
)
SOURCE_LOCK = ROOT / "PRODUCTION-SOURCE-LOCK.yaml"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,191}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
ZERO_SHA = "0" * 40
ZERO_HASH = "0" * 64
ZERO_DIGEST = "sha256:" + ZERO_HASH

REQUIRED_VARIABLES = {
    "CODESTRA_STAGING_OPERATOR_HOST",
    "CODESTRA_STAGING_OPERATOR_USER",
    "CODESTRA_STAGING_OPERATOR_PORT",
    "CODESTRA_STAGING_CANDIDATE_ID",
    "CODESTRA_STAGING_CANDIDATE_MANIFEST_SHA256",
    "CODESTRA_STAGING_ENDPOINT_MANIFEST_SHA256",
    "CODESTRA_STAGING_KEYCLOAK_ISSUER",
    "CODESTRA_STAGING_OFF_HOST_BACKUP_URI",
    "CODESTRA_STAGING_CANARY_MAX_PERCENT",
    "CODESTRA_STAGING_KONG_ROUTE_COUNT",
}
REQUIRED_SECRETS = {
    "CODESTRA_STAGING_READONLY_OPERATOR_SSH_KEY",
    "CODESTRA_STAGING_READONLY_OPERATOR_KNOWN_HOSTS",
    "CODESTRA_GHCR_DEPLOYMENT_READ_TOKEN",
    "CODESTRA_STAGING_READONLY_ENDPOINT_MANIFEST",
    "CODESTRA_STAGING_READONLY_BEARER_TOKEN",
    "CODESTRA_STAGING_METRICS_BEARER_TOKEN",
    "CODESTRA_STAGING_OFF_HOST_BACKUP_CREDENTIAL",
    "CODESTRA_RELEASE_SIGNING_PUBLIC_KEY",
}
REQUIRED_CHECKS = {
    "source_version_readback",
    "readiness",
    "fail_closed_capabilities",
    "protected_metrics",
    "keycloak_issuer",
    "kong_29_route_smoke",
    "database_migration_state",
    "zero_calls",
    "zero_emails",
    "zero_sms",
    "zero_provider_effects",
    "monitoring_continuity",
    "latency_error_budget",
    "write_method_denial",
    "database_backup",
    "odoo_filestore_backup",
    "configuration_backup",
    "off_host_backup_copy",
    "rollback_rehearsal",
    "rollback_data_integrity",
}
REQUIRED_FALSE_CONTROLS = {
    "LIVE_WRITE",
    "ODOO_WRITE",
    "ENABLE_EXTERNAL_DELIVERY",
    "N8N_DELIVERY_ENABLED",
    "LIVE_EMAIL_DELIVERY",
    "LIVE_SMS_DELIVERY",
    "LIVE_PSTN_DIALING",
    "PRODUCTION_DIALING",
    "CAMPAIGN_ACTIVATION",
    "PROVIDER_DELIVERY",
    "ADVERTISING_ACTIVATION",
    "PAYMENT_EXECUTION",
    "FINANCIAL_TRADING",
}
REQUIRED_ABORTS = {
    "source_sha_mismatch",
    "image_digest_mismatch",
    "readiness_failure",
    "monitoring_loss",
    "database_migration_drift",
    "latency_regression",
    "error_rate_regression",
    "write_request_observed",
    "call_counter_moved",
    "email_counter_moved",
    "sms_counter_moved",
    "provider_effect_counter_moved",
    "backup_or_restore_integrity_failure",
}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE", "CONNECT", "TRACE"}


class ValidationError(ValueError):
    """Raised for malformed validator input, never for a secret value."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return value


def top_level_scalar(path: Path, key: str) -> str | None:
    """Read one unindented scalar from a simple YAML authority document."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc
    prefix = f"{key}:"
    values = []
    for raw in lines:
        if raw.startswith(prefix):
            value = raw[len(prefix) :].split("#", 1)[0].strip().strip("'\"")
            values.append(value)
    if len(values) != 1:
        raise ValidationError(
            f"{path} must contain exactly one top-level {key!r} scalar"
        )
    return values[0]


def is_placeholder(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().upper()
    return (
        not normalized
        or normalized in {ZERO_SHA, ZERO_HASH, ZERO_DIGEST.upper()}
        or "REPLACE_WITH" in normalized
        or normalized.startswith("TODO")
        or normalized.startswith("TBD")
        or normalized == "UNKNOWN"
        or normalized == "PENDING"
    )


def validate_https_url(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or is_placeholder(value):
        errors.append(f"{label} must be a non-placeholder HTTPS URL")
        return
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        errors.append(
            f"{label} must use credential-free HTTPS without query or fragment"
        )


def validate_false_controls(
    controls: object,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(controls, dict):
        errors.append(f"{label} must be an object")
        return
    actual = set(controls)
    if actual != REQUIRED_FALSE_CONTROLS:
        missing = sorted(REQUIRED_FALSE_CONTROLS - actual)
        extra = sorted(actual - REQUIRED_FALSE_CONTROLS)
        if missing:
            errors.append(f"{label} is missing controls: {', '.join(missing)}")
        if extra:
            errors.append(f"{label} has unknown controls: {', '.join(extra)}")
    for name in sorted(REQUIRED_FALSE_CONTROLS & actual):
        if controls.get(name) is not False:
            errors.append(f"{label}.{name} must remain false")


def validate_canary(canary: object, label: str, errors: list[str]) -> None:
    if not isinstance(canary, dict):
        errors.append(f"{label} must be an object")
        return
    maximum = canary.get("maximum_traffic_percent")
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)):
        errors.append(f"{label}.maximum_traffic_percent must be numeric")
    elif maximum <= 0 or maximum > 1:
        errors.append(f"{label}.maximum_traffic_percent must be > 0 and <= 1")
    if canary.get("allowed_methods") != ["GET", "HEAD"]:
        errors.append(f"{label}.allowed_methods must be exactly GET and HEAD")
    denied = canary.get("denied_methods")
    if not isinstance(denied, list) or set(denied) != WRITE_METHODS:
        errors.append(f"{label}.denied_methods must contain every governed write method")
    if canary.get("automatic_rollback_required") is not True:
        errors.append(f"{label}.automatic_rollback_required must be true")


def validate_authority(authority: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if authority.get("schema_version") != 1:
        errors.append("authority schema_version must equal 1")
    if authority.get("authority_id") != "codestra.staging-readonly.v1":
        errors.append("authority_id must equal codestra.staging-readonly.v1")
    if authority.get("repository") != "appolon1908-hue/codestra-production-platform":
        errors.append("authority repository is not the canonical platform repository")
    if authority.get("environment") != "staging-readonly":
        errors.append("authority environment must equal staging-readonly")
    if authority.get("environment_protection_required") is not True:
        errors.append("staging-readonly environment protection must be required")
    if authority.get("production_changed") is not False:
        errors.append("repository authority must not claim a production change")

    if set(authority.get("required_variables") or []) != REQUIRED_VARIABLES:
        errors.append("required_variables does not match the reviewed inventory")
    if len(authority.get("required_variables") or []) != len(REQUIRED_VARIABLES):
        errors.append("required_variables contains duplicates")
    if set(authority.get("required_secrets") or []) != REQUIRED_SECRETS:
        errors.append("required_secrets does not match the reviewed inventory")
    if len(authority.get("required_secrets") or []) != len(REQUIRED_SECRETS):
        errors.append("required_secrets contains duplicates")

    checks = authority.get("required_checks")
    if not isinstance(checks, list):
        errors.append("required_checks must be a list")
    else:
        ids = [item.get("id") for item in checks if isinstance(item, dict)]
        if set(ids) != REQUIRED_CHECKS or len(ids) != len(REQUIRED_CHECKS):
            errors.append("required_checks does not match the reviewed exact check set")
        for item in checks:
            if not isinstance(item, dict):
                errors.append("every required check must be an object")
                continue
            if item.get("required") is not True:
                errors.append(f"required check {item.get('id')} must be mandatory")
            if item.get("live_effect_allowed") is not False:
                errors.append(
                    f"required check {item.get('id')} must prohibit live effects"
                )

    validate_false_controls(authority.get("safety_controls"), "safety_controls", errors)
    validate_canary(authority.get("canary"), "canary", errors)
    canary = authority.get("canary") or {}
    for key in (
        "same_source_and_digest_required",
        "separate_authorization_required",
        "automatic_rollback_required",
    ):
        if not isinstance(canary, dict) or canary.get(key) is not True:
            errors.append(f"canary.{key} must be true")

    aborts = authority.get("abort_conditions")
    if not isinstance(aborts, list) or set(aborts) != REQUIRED_ABORTS:
        errors.append("abort_conditions does not match the reviewed fail-closed set")
    if isinstance(aborts, list) and len(aborts) != len(REQUIRED_ABORTS):
        errors.append("abort_conditions contains duplicates")

    source_lock = authority.get("source_lock")
    runtime = authority.get("runtime_candidate")
    infrastructure = authority.get("staging_infrastructure")
    for name, value in (
        ("source_lock", source_lock),
        ("runtime_candidate", runtime),
        ("staging_infrastructure", infrastructure),
    ):
        if not isinstance(value, dict):
            errors.append(f"{name} must be an object")

    actual_source_status = None
    if isinstance(source_lock, dict):
        if source_lock.get("required_status") != "PASS":
            errors.append("source_lock.required_status must equal PASS")
        if source_lock.get("path") != "PRODUCTION-SOURCE-LOCK.yaml":
            errors.append("source_lock.path must name PRODUCTION-SOURCE-LOCK.yaml")
        try:
            actual_source_status = top_level_scalar(SOURCE_LOCK, "status")
        except ValidationError as exc:
            errors.append(str(exc))
        if actual_source_status and source_lock.get("observed_status") != actual_source_status:
            errors.append(
                "source_lock.observed_status does not match the committed source lock"
            )
        observed_commit = source_lock.get("observed_commit")
        if not isinstance(observed_commit, str) or not SHA_RE.fullmatch(observed_commit):
            errors.append("source_lock.observed_commit must be an exact Git SHA")
        if source_lock.get("fail_closed_on_unknown_or_pending") is not True:
            errors.append("source lock must fail closed on unknown or pending evidence")

    blocked = actual_source_status != "PASS"
    if isinstance(runtime, dict):
        if runtime.get("required_deployment_authorized") is not True:
            errors.append("runtime candidate must require deployment authorization")
        if runtime.get("observed_deployment_authorized") is not True:
            blocked = True
        ref = runtime.get("ref")
        if not isinstance(ref, str) or not SHA_RE.fullmatch(ref):
            errors.append("runtime_candidate.ref must be an exact Git SHA")
    if isinstance(infrastructure, dict):
        if infrastructure.get("required_host_status") != "CREATED_AND_VERIFIED":
            errors.append("staging infrastructure required status changed")
        if infrastructure.get("observed_host_status") != "CREATED_AND_VERIFIED":
            blocked = True
        ref = infrastructure.get("ref")
        if not isinstance(ref, str) or not SHA_RE.fullmatch(ref):
            errors.append("staging_infrastructure.ref must be an exact Git SHA")

    if blocked:
        if authority.get("execution_status") != "BLOCKED":
            errors.append("blocked prerequisites require execution_status=BLOCKED")
        if authority.get("deployment_authorized") is not False:
            errors.append("blocked prerequisites require deployment_authorized=false")
        if authority.get("production_canary_authorized") is not False:
            errors.append("blocked prerequisites require production_canary_authorized=false")
        blockers = authority.get("blockers")
        if not isinstance(blockers, list) or not blockers:
            errors.append("blocked authority must enumerate its blockers")
    return errors


def validate_component_list(
    value: object,
    label: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list) or not value:
        errors.append(f"{label} must be a non-empty component list")
        return output
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        name = item.get("name")
        repository = item.get("repository")
        source_sha = item.get("source_sha")
        image = item.get("image")
        digest = item.get("image_digest")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            errors.append(f"{item_label}.name is invalid")
            continue
        if name in output:
            errors.append(f"duplicate component name: {name}")
        output[name] = item
        if not isinstance(repository, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
        ):
            errors.append(f"{item_label}.repository must be owner/name")
        if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha) or source_sha == ZERO_SHA:
            errors.append(f"{item_label}.source_sha must be a non-zero exact SHA")
        if not isinstance(image, str) or "@" in image or ":latest" in image:
            errors.append(f"{item_label}.image must be an untagged registry repository")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest) or digest == ZERO_DIGEST:
            errors.append(f"{item_label}.image_digest must be a non-zero OCI digest")
        if item.get("rebuild_allowed") is not False:
            errors.append(f"{item_label}.rebuild_allowed must be false")
        if item.get("retag_allowed") is not False:
            errors.append(f"{item_label}.retag_allowed must be false")
    return output


def validate_manifest(
    manifest: dict[str, Any],
    authority: dict[str, Any],
    *,
    allow_template: bool,
) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("endpoint manifest schema_version must equal 1")
    if manifest.get("environment") != "staging-readonly":
        errors.append("endpoint manifest environment must equal staging-readonly")
    is_template = manifest.get("template") is True
    if allow_template:
        if not is_template:
            errors.append("committed endpoint manifest must remain a template")
    elif manifest.get("template") is not False:
        errors.append("materialized endpoint manifest must set template=false")

    validate_false_controls(
        manifest.get("safety_controls"),
        "endpoint_manifest.safety_controls",
        errors,
    )
    validate_canary(manifest.get("canary"), "endpoint_manifest.canary", errors)

    credentials = manifest.get("credential_policy")
    if not isinstance(credentials, dict):
        errors.append("credential_policy must be an object")
    else:
        if credentials.get("credentials_embedded") is not False:
            errors.append("endpoint manifest must not embed credentials")
        if credentials.get("bearer_credential_ref") != "CODESTRA_STAGING_READONLY_BEARER_TOKEN":
            errors.append("bearer credential reference changed")
        if credentials.get("metrics_credential_ref") != "CODESTRA_STAGING_METRICS_BEARER_TOKEN":
            errors.append("metrics credential reference changed")

    backups = manifest.get("backups")
    if not isinstance(backups, dict):
        errors.append("backups must be an object")
    else:
        for key in (
            "database_required",
            "odoo_filestore_required",
            "configuration_required",
            "off_host_copy_required",
        ):
            if backups.get(key) is not True:
                errors.append(f"backups.{key} must be true")
        if backups.get("credential_ref") != "CODESTRA_STAGING_OFF_HOST_BACKUP_CREDENTIAL":
            errors.append("off-host backup credential reference changed")

    rollback = manifest.get("rollback")
    if not isinstance(rollback, dict):
        errors.append("rollback must be an object")
    else:
        for key in (
            "previous_candidate_required",
            "health_readback_required",
            "readiness_readback_required",
            "version_readback_required",
            "data_integrity_required",
        ):
            if rollback.get(key) is not True:
                errors.append(f"rollback.{key} must be true")
        for key in ("rto_seconds_limit", "rpo_seconds_limit"):
            value = rollback.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"rollback.{key} must be a positive integer")

    counters = manifest.get("counters")
    if not isinstance(counters, dict) or set(counters) != {
        "calls",
        "emails",
        "sms",
        "provider_effects",
    }:
        errors.append("counters must contain calls, emails, sms, and provider_effects")
    else:
        for name, counter in counters.items():
            if not isinstance(counter, dict):
                errors.append(f"counters.{name} must be an object")
                continue
            baseline = counter.get("baseline")
            if isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
                errors.append(f"counters.{name}.baseline must be a non-negative integer")
            if counter.get("maximum_delta") != 0:
                errors.append(f"counters.{name}.maximum_delta must equal zero")

    if allow_template:
        candidate = manifest.get("candidate")
        previous = manifest.get("previous_candidate")
        if not isinstance(candidate, dict) or not isinstance(previous, dict):
            errors.append("template candidate identities must be objects")
        if manifest.get("kong", {}).get("route_count") != 29:
            errors.append("template must preserve the 29-route Kong denominator")
        return errors

    candidate = manifest.get("candidate")
    previous = manifest.get("previous_candidate")
    if not isinstance(candidate, dict):
        errors.append("candidate must be an object")
        candidate = {}
    if not isinstance(previous, dict):
        errors.append("previous_candidate must be an object")
        previous = {}

    release_id = candidate.get("release_id")
    if not isinstance(release_id, str) or not NAME_RE.fullmatch(release_id) or is_placeholder(release_id):
        errors.append("candidate.release_id must be a non-placeholder release identity")
    source_sha = candidate.get("platform_source_sha")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha) or source_sha == ZERO_SHA:
        errors.append("candidate.platform_source_sha must be a non-zero exact SHA")
    for key in ("source_lock_sha256", "candidate_manifest_sha256"):
        value = candidate.get(key)
        if not isinstance(value, str) or not HASH_RE.fullmatch(value) or value == ZERO_HASH:
            errors.append(f"candidate.{key} must be a non-zero SHA-256")

    current_components = validate_component_list(
        candidate.get("components"), "candidate.components", errors
    )
    previous_release = previous.get("release_id")
    if not isinstance(previous_release, str) or not NAME_RE.fullmatch(previous_release) or is_placeholder(previous_release):
        errors.append("previous_candidate.release_id must be non-placeholder")
    previous_components = validate_component_list(
        previous.get("components"), "previous_candidate.components", errors
    )
    if current_components and previous_components and set(current_components) != set(previous_components):
        errors.append("candidate and previous_candidate component sets must match")

    identity = manifest.get("identity")
    if not isinstance(identity, dict):
        errors.append("identity must be an object")
    else:
        validate_https_url(identity.get("issuer"), "identity.issuer", errors)
        if identity.get("discovery_path") != "/.well-known/openid-configuration":
            errors.append("identity.discovery_path changed")
        if identity.get("expected_http_status") != 200:
            errors.append("identity discovery must require HTTP 200")

    targets = manifest.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append("targets must be a non-empty list")
    else:
        target_ids: set[str] = set()
        for index, target in enumerate(targets):
            label = f"targets[{index}]"
            if not isinstance(target, dict):
                errors.append(f"{label} must be an object")
                continue
            target_id = target.get("id")
            if not isinstance(target_id, str) or not NAME_RE.fullmatch(target_id):
                errors.append(f"{label}.id is invalid")
            elif target_id in target_ids:
                errors.append(f"duplicate target id: {target_id}")
            else:
                target_ids.add(target_id)
            validate_https_url(target.get("base_url"), f"{label}.base_url", errors)
            for key in (
                "health_path",
                "readiness_path",
                "version_path",
                "capabilities_path",
                "metrics_path",
            ):
                value = target.get(key)
                if not isinstance(value, str) or not value.startswith("/") or "?" in value:
                    errors.append(f"{label}.{key} must be an absolute query-free path")
            if target.get("allowed_methods") != ["GET", "HEAD"]:
                errors.append(f"{label}.allowed_methods must be GET and HEAD only")

    kong = manifest.get("kong")
    if not isinstance(kong, dict):
        errors.append("kong must be an object")
    else:
        validate_https_url(kong.get("base_url"), "kong.base_url", errors)
        if kong.get("route_count") != 29:
            errors.append("kong.route_count must equal 29")
        routes = kong.get("routes")
        if not isinstance(routes, list) or len(routes) != 29:
            errors.append("kong.routes must enumerate exactly 29 routes")
        else:
            route_ids: set[str] = set()
            for index, route in enumerate(routes):
                label = f"kong.routes[{index}]"
                if not isinstance(route, dict):
                    errors.append(f"{label} must be an object")
                    continue
                route_id = route.get("id")
                if not isinstance(route_id, str) or not NAME_RE.fullmatch(route_id):
                    errors.append(f"{label}.id is invalid")
                elif route_id in route_ids:
                    errors.append(f"duplicate Kong route id: {route_id}")
                else:
                    route_ids.add(route_id)
                if route.get("method") not in {"GET", "HEAD"}:
                    errors.append(f"{label}.method must be read-only")
                path = route.get("path")
                if not isinstance(path, str) or not path.startswith("/") or "?" in path:
                    errors.append(f"{label}.path must be an absolute query-free path")
                statuses = route.get("expected_status")
                if not isinstance(statuses, list) or not statuses or not all(
                    isinstance(value, int) and 100 <= value <= 599 for value in statuses
                ):
                    errors.append(f"{label}.expected_status must be a non-empty status list")

    database = manifest.get("database")
    if not isinstance(database, dict):
        errors.append("database must be an object")
    else:
        validate_https_url(
            database.get("migration_evidence_endpoint"),
            "database.migration_evidence_endpoint",
            errors,
        )
        heads = database.get("expected_heads")
        if not isinstance(heads, list) or not heads or not all(
            isinstance(value, str) and NAME_RE.fullmatch(value) for value in heads
        ):
            errors.append("database.expected_heads must be a non-empty identity list")

    return errors


def presence_flag(secret_name: str) -> bool:
    value = os.environ.get(f"HAS_{secret_name}", "")
    return value.strip().lower() == "true"


def validate_environment(
    authority: dict[str, Any],
    endpoint_manifest_path: Path | None,
) -> tuple[list[str], dict[str, Any]]:
    errors = validate_authority(authority)
    missing_variables = sorted(
        name for name in REQUIRED_VARIABLES if not os.environ.get(name, "").strip()
    )
    missing_secrets = sorted(name for name in REQUIRED_SECRETS if not presence_flag(name))
    invalid_variables: list[str] = []

    host = os.environ.get("CODESTRA_STAGING_OPERATOR_HOST", "").strip()
    if host and (
        "://" in host
        or any(character.isspace() for character in host)
        or "/" in host
        or "@" in host
    ):
        invalid_variables.append("CODESTRA_STAGING_OPERATOR_HOST")
    user = os.environ.get("CODESTRA_STAGING_OPERATOR_USER", "").strip()
    if user and not USER_RE.fullmatch(user):
        invalid_variables.append("CODESTRA_STAGING_OPERATOR_USER")
    port = os.environ.get("CODESTRA_STAGING_OPERATOR_PORT", "").strip()
    if port:
        try:
            parsed_port = int(port)
        except ValueError:
            parsed_port = 0
        if parsed_port < 1 or parsed_port > 65535:
            invalid_variables.append("CODESTRA_STAGING_OPERATOR_PORT")

    for name in (
        "CODESTRA_STAGING_CANDIDATE_MANIFEST_SHA256",
        "CODESTRA_STAGING_ENDPOINT_MANIFEST_SHA256",
    ):
        value = os.environ.get(name, "").strip()
        if value and (not HASH_RE.fullmatch(value) or value == ZERO_HASH):
            invalid_variables.append(name)

    candidate_id = os.environ.get("CODESTRA_STAGING_CANDIDATE_ID", "").strip()
    if candidate_id and (not NAME_RE.fullmatch(candidate_id) or is_placeholder(candidate_id)):
        invalid_variables.append("CODESTRA_STAGING_CANDIDATE_ID")

    issuer = os.environ.get("CODESTRA_STAGING_KEYCLOAK_ISSUER", "").strip()
    if issuer:
        issuer_errors: list[str] = []
        validate_https_url(issuer, "CODESTRA_STAGING_KEYCLOAK_ISSUER", issuer_errors)
        if issuer_errors:
            invalid_variables.append("CODESTRA_STAGING_KEYCLOAK_ISSUER")

    off_host_uri = os.environ.get("CODESTRA_STAGING_OFF_HOST_BACKUP_URI", "").strip()
    if off_host_uri:
        parsed = urlsplit(off_host_uri)
        if (
            parsed.scheme not in {"s3", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            invalid_variables.append("CODESTRA_STAGING_OFF_HOST_BACKUP_URI")

    canary_value = os.environ.get("CODESTRA_STAGING_CANARY_MAX_PERCENT", "").strip()
    if canary_value:
        try:
            canary_percent = float(canary_value)
        except ValueError:
            canary_percent = 0
        if canary_percent <= 0 or canary_percent > 1:
            invalid_variables.append("CODESTRA_STAGING_CANARY_MAX_PERCENT")

    route_count = os.environ.get("CODESTRA_STAGING_KONG_ROUTE_COUNT", "").strip()
    if route_count and route_count != "29":
        invalid_variables.append("CODESTRA_STAGING_KONG_ROUTE_COUNT")

    if missing_variables:
        errors.append("missing required environment variables")
    if missing_secrets:
        errors.append("missing required encrypted environment secrets")
    if invalid_variables:
        errors.append("one or more environment variables are invalid")

    manifest: dict[str, Any] | None = None
    manifest_errors: list[str] = []
    if endpoint_manifest_path is None or not endpoint_manifest_path.is_file():
        manifest_errors.append("materialized endpoint manifest is missing")
    else:
        try:
            manifest_bytes = endpoint_manifest_path.read_bytes()
            if not manifest_bytes:
                manifest_errors.append("materialized endpoint manifest is empty")
            else:
                expected_hash = os.environ.get(
                    "CODESTRA_STAGING_ENDPOINT_MANIFEST_SHA256", ""
                ).strip()
                actual_hash = hashlib.sha256(manifest_bytes).hexdigest()
                if expected_hash and actual_hash != expected_hash:
                    manifest_errors.append(
                        "materialized endpoint manifest SHA-256 does not match the environment variable"
                    )
                manifest = json.loads(manifest_bytes.decode("utf-8"))
                if not isinstance(manifest, dict):
                    manifest_errors.append("materialized endpoint manifest must be a JSON object")
                    manifest = None
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            manifest_errors.append(f"cannot parse materialized endpoint manifest: {exc}")

    if manifest is not None:
        manifest_errors.extend(validate_manifest(manifest, authority, allow_template=False))
        candidate = manifest.get("candidate") or {}
        if candidate_id and candidate.get("release_id") != candidate_id:
            manifest_errors.append("candidate release identity does not match environment variable")
        candidate_hash = os.environ.get(
            "CODESTRA_STAGING_CANDIDATE_MANIFEST_SHA256", ""
        ).strip()
        if candidate_hash and candidate.get("candidate_manifest_sha256") != candidate_hash:
            manifest_errors.append("candidate manifest SHA-256 does not match environment variable")
        if issuer and (manifest.get("identity") or {}).get("issuer") != issuer:
            manifest_errors.append("Keycloak issuer does not match environment variable")

    errors.extend(manifest_errors)

    source_status = None
    try:
        source_status = top_level_scalar(SOURCE_LOCK, "status")
    except ValidationError as exc:
        errors.append(str(exc))
    runtime = authority.get("runtime_candidate") or {}
    infrastructure = authority.get("staging_infrastructure") or {}
    if source_status != "PASS":
        errors.append("production source lock is not PASS")
    if runtime.get("observed_deployment_authorized") is not True:
        errors.append("runtime candidate is not deployment-authorized")
    if infrastructure.get("observed_host_status") != "CREATED_AND_VERIFIED":
        errors.append("staging host is not created and verified")
    if authority.get("execution_status") != "READY":
        errors.append("staging execution authority is not READY")
    if authority.get("deployment_authorized") is not True:
        errors.append("staging deployment is not authorized")

    evidence = {
        "schema_version": 1,
        "environment": "staging-readonly",
        "status": "PASS" if not errors else "BLOCKED",
        "production_changed": False,
        "runtime_contacted": False,
        "ssh_attempted": False,
        "secret_values_recorded": False,
        "source_lock_status": source_status,
        "execution_status": authority.get("execution_status"),
        "deployment_authorized": authority.get("deployment_authorized"),
        "runtime_candidate_authorized": runtime.get("observed_deployment_authorized"),
        "staging_host_status": infrastructure.get("observed_host_status"),
        "missing_variables": missing_variables,
        "missing_secrets": missing_secrets,
        "invalid_variables": sorted(set(invalid_variables)),
        "endpoint_manifest_present": endpoint_manifest_path is not None
        and endpoint_manifest_path.is_file(),
        "endpoint_manifest_valid": not manifest_errors,
        "blockers": sorted(set(errors)),
    }
    return errors, evidence


def write_evidence(path: Path | None, evidence: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("policy", "environment"), default="policy")
    parser.add_argument("--authority", type=Path, default=DEFAULT_AUTHORITY)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--endpoint-manifest", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        authority = load_json(args.authority)
        if args.mode == "policy":
            errors = validate_authority(authority)
            template = load_json(args.template)
            errors.extend(validate_manifest(template, authority, allow_template=True))
            evidence = {
                "schema_version": 1,
                "mode": "policy",
                "environment": "staging-readonly",
                "status": "PASS" if not errors else "FAIL",
                "production_changed": False,
                "runtime_contacted": False,
                "ssh_attempted": False,
                "secret_values_recorded": False,
                "errors": errors,
            }
        else:
            errors, evidence = validate_environment(authority, args.endpoint_manifest)
            evidence["mode"] = "environment"
        write_evidence(args.evidence_output, evidence)
    except ValidationError as exc:
        errors = [str(exc)]
        write_evidence(
            args.evidence_output,
            {
                "schema_version": 1,
                "mode": args.mode,
                "environment": "staging-readonly",
                "status": "FAIL",
                "production_changed": False,
                "runtime_contacted": False,
                "ssh_attempted": False,
                "secret_values_recorded": False,
                "errors": errors,
            },
        )

    if errors:
        for error in errors:
            print(f"STAGING_READONLY_BLOCKER={error}", file=sys.stderr)
        print("STAGING_READONLY_GATE=BLOCKED")
        return 1
    print("STAGING_READONLY_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
