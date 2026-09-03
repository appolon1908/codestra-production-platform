#!/usr/bin/env python3
"""Validate the disabled-by-default OpenAI provider runtime contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE = ROOT / "deploy" / "middleware" / "compose.openai-provider.yaml"
DEFAULT_LOCK = ROOT / "deploy" / "middleware" / "openai-provider-release-lock.json"
DEFAULT_APPROVED_LOCK = ROOT / "deploy" / "middleware" / "approved-release-lock.json"
SERVICE = "middleware-openai-provider-worker"
PROFILE = "openai-provider"
BLOCKED_STATUS = "BLOCKED_PENDING_PROTECTED_SECRETS_REGISTRATION_AND_STAGING_CANARY"
DIGEST_IMAGE_RE = re.compile(
    r"^ghcr\.io/appolon1908-hue/codestra-middleware@sha256:[0-9a-f]{64}$"
)
SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_FALSE_FLAGS = {
    "OPENAI_PROVIDER_ENABLED",
    "AI_SUBMISSIONS_ENABLED",
    "AI_ORCHESTRATION_ENABLED",
    "AI_WORKER_CLAIMS_ENABLED",
    "SEND_EVENTS",
    "ENABLE_EXTERNAL_DELIVERY",
    "LIVE_WRITES_ENABLED",
    "ODOO_WRITE_ENABLED",
    "ODOO_DELIVERY_ENABLED",
    "N8N_DELIVERY_ENABLED",
    "CALLBACK_DISPATCH_ENABLED",
    "LIVE_EMAIL_DELIVERY",
    "LIVE_SMS_DELIVERY",
    "LIVE_PSTN_DIALING",
    "GENERAL_AI_DIALING",
}
EXPECTED_ENVIRONMENT = {
    "ENVIRONMENT": "production",
    "SERVICE_NAME": SERVICE,
    "DATABASE_URL_FILE": "/run/secrets/database_url",
    "OPENAI_API_KEY_FILE": "/run/secrets/openai/api-key",
    "OPENAI_SAFETY_SALT_FILE": "/run/secrets/openai/safety-salt",
    "AI_JOB_PROJECT_ALLOWLIST": "codestra-ai-console",
    "OPENAI_WORKER_SERVICE_ID": "openai-responses-provider",
    "OPENAI_WORKER_ID": "codestra-openai-01",
    "OPENAI_WORKER_MAX_CONCURRENCY": "1",
    "OPENAI_CHAT_REASONING_EFFORT": "low",
    "OPENAI_CODING_REASONING_EFFORT": "medium",
    "OPENAI_REQUEST_TIMEOUT_SECONDS": "120",
    "OPENAI_MAX_RETRIES": "2",
    "OPENAI_DAILY_USER_TOKEN_LIMIT": "100000",
    "OPENAI_DAILY_PROJECT_TOKEN_LIMIT": "250000",
    "OPENAI_MAX_ESTIMATED_COST_MICRO_USD": "300000",
}
EXPECTED_MOUNTS = {
    "/etc/codestra/secrets/middleware-runtime/middleware-integration-api-database-url": (
        "/run/secrets/database_url"
    ),
    "/etc/codestra/secrets/openai-provider/api-key": "/run/secrets/openai/api-key",
    "/etc/codestra/secrets/openai-provider/safety-salt": "/run/secrets/openai/safety-salt",
}
REQUIRED_EVIDENCE = {
    "exact source SHA and image digest readback",
    "required database migration head",
    "protected secret metadata without values",
    "enabled exact worker registration with concurrency one",
    "provider model-access probe without prompt or response retention",
    "TLS egress restricted to api.openai.com:443",
    "authenticated chat and coding canary",
    (
        "streaming, cancellation, timeout, tenant-denial, project-denial, "
        "quota, and provider-failure tests"
    ),
    "zero calls, zero emails, and zero SMS",
    "rollback to the previously certified Qwen worker",
    "independent approval on the exact deployment head",
}
FORBIDDEN_SERVICE_KEYS = {
    "build", "devices", "env_file", "expose", "ipc", "network_mode", "pid",
    "ports", "privileged", "volumes_from",
}
FORBIDDEN_ENVIRONMENT_KEYS = {"DATABASE_URL", "OPENAI_API_KEY", "OPENAI_SAFETY_SALT"}


class ContractError(ValueError):
    """A bounded validation failure."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {path.name}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path.name} must contain an object")
    return value


def load_yaml(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
        value = yaml.safe_load(text)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot load {path.name}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path.name} must contain an object")
    return value, text


def require_equal(actual: object, expected: object, label: str, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"{label} mismatch")


def validate_mounts(value: object, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) != len(EXPECTED_MOUNTS):
        errors.append("service volumes must be the exact three protected bind mounts")
        return
    observed: dict[str, str] = {}
    for index, mount in enumerate(value):
        label = f"service volumes[{index}]"
        if not isinstance(mount, dict):
            errors.append(f"{label} must use long bind-mount syntax")
            continue
        if mount.get("type") != "bind":
            errors.append(f"{label}.type must be bind")
        source, target = mount.get("source"), mount.get("target")
        if isinstance(source, str) and isinstance(target, str):
            observed[source] = target
        else:
            errors.append(f"{label} source and target must be strings")
        if mount.get("read_only") is not True:
            errors.append(f"{label} must be read-only")
        bind = mount.get("bind")
        if not isinstance(bind, dict) or bind.get("create_host_path") is not False:
            errors.append(f"{label} must disable host-path creation")
    if observed != EXPECTED_MOUNTS:
        errors.append("service protected bind-mount set mismatch")


def validate_contract(
    compose: dict[str, Any],
    compose_text: str,
    release_lock: dict[str, Any],
    approved_lock: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    revision = approved_lock.get("revision")
    image = approved_lock.get("image")
    database_head = approved_lock.get("required_database_head")
    if not isinstance(revision, str) or SOURCE_SHA_RE.fullmatch(revision) is None:
        errors.append("approved release revision is not an exact source SHA")
    if not isinstance(image, str) or DIGEST_IMAGE_RE.fullmatch(image) is None:
        errors.append("approved release image is not an immutable Middleware digest")

    require_equal(release_lock.get("source_revision"), revision, "OpenAI source revision binding", errors)
    require_equal(release_lock.get("source_tree"), approved_lock.get("source_tree"), "OpenAI source tree binding", errors)
    require_equal(release_lock.get("image"), image, "OpenAI image binding", errors)
    require_equal(release_lock.get("required_database_head"), database_head, "OpenAI database-head binding", errors)
    require_equal(release_lock.get("compose_file"), "deploy/middleware/compose.openai-provider.yaml", "OpenAI compose path", errors)
    require_equal(release_lock.get("compose_profile"), PROFILE, "OpenAI profile", errors)
    require_equal(release_lock.get("service"), SERVICE, "OpenAI service", errors)
    require_equal(release_lock.get("container_user"), "10001:10001", "OpenAI container user", errors)

    identity = release_lock.get("worker_identity")
    if not isinstance(identity, dict):
        errors.append("worker_identity must be an object")
    else:
        require_equal(identity.get("worker_id"), "codestra-openai-01", "worker identity", errors)
        require_equal(identity.get("service_id"), "openai-responses-provider", "worker service identity", errors)
        require_equal(identity.get("max_concurrency"), 1, "worker concurrency", errors)
        require_equal(identity.get("project_allowlist"), ["codestra-ai-console"], "worker project allowlist", errors)

    activation = release_lock.get("activation")
    if not isinstance(activation, dict):
        errors.append("activation must be an object")
    else:
        require_equal(activation.get("status"), BLOCKED_STATUS, "activation status", errors)
        for key in (
            "base_provider_enabled",
            "base_submissions_enabled",
            "base_orchestration_enabled",
            "base_worker_claims_enabled",
            "activation_overlay_committed",
            "production_effect_on_merge",
        ):
            require_equal(activation.get(key), False, f"activation {key}", errors)
        if set(activation.get("required_evidence", [])) != REQUIRED_EVIDENCE:
            errors.append("activation required evidence set mismatch")

    rollback = release_lock.get("rollback")
    if not isinstance(rollback, dict):
        errors.append("rollback must be an object")
    else:
        require_equal(rollback.get("provider"), "qwen", "rollback provider", errors)
        require_equal(rollback.get("active_lease_must_be_zero"), True, "rollback active lease gate", errors)
        require_equal(rollback.get("openai_new_claims_disabled_first"), True, "rollback new-claim gate", errors)

    services = compose.get("services")
    if not isinstance(services, dict) or set(services) != {SERVICE}:
        errors.append("compose must define only the governed OpenAI worker")
        return errors
    service = services[SERVICE]
    if not isinstance(service, dict):
        errors.append("governed OpenAI worker must be an object")
        return errors

    require_equal(service.get("profiles"), [PROFILE], "service profile", errors)
    service_image = service.get("image")
    if isinstance(service_image, str) and ":latest" in service_image:
        errors.append("mutable latest reference is forbidden")
    require_equal(service_image, image, "service image", errors)
    require_equal(service.get("command"), ["python", "-m", "app.entrypoints.openai_worker"], "service command", errors)
    require_equal(service.get("user"), "10001:10001", "service user", errors)
    require_equal(service.get("init"), True, "service init", errors)
    require_equal(service.get("restart"), "no", "service restart policy", errors)
    require_equal(service.get("read_only"), True, "service read-only root", errors)
    require_equal(service.get("cap_drop"), ["ALL"], "service capability drop", errors)
    if "no-new-privileges:true" not in (service.get("security_opt") or []):
        errors.append("service must enable no-new-privileges")
    for key in FORBIDDEN_SERVICE_KEYS:
        if key in service:
            errors.append(f"service must not define {key}")
    if service.get("networks") != ["middleware_backend"]:
        errors.append("service must use only middleware_backend")

    environment = service.get("environment")
    if not isinstance(environment, dict):
        errors.append("service environment must be an object")
    else:
        for key, expected in EXPECTED_ENVIRONMENT.items():
            require_equal(environment.get(key), expected, f"environment {key}", errors)
        for key in REQUIRED_FALSE_FLAGS:
            require_equal(environment.get(key), "false", f"environment {key}", errors)
        for key in FORBIDDEN_ENVIRONMENT_KEYS:
            if key in environment:
                errors.append(f"raw secret environment key forbidden: {key}")
        if "OPENAI_CHAT_MODEL" in environment or "OPENAI_CODING_MODEL" in environment:
            errors.append("model identifiers must remain source-locked and be runtime-probed")
    validate_mounts(service.get("volumes"), errors)

    if re.search(r"(?m)^\s*OPENAI_API_KEY\s*:", compose_text):
        errors.append("raw OPENAI_API_KEY environment entry is forbidden")
    if re.search(r"(?m)^\s*OPENAI_SAFETY_SALT\s*:", compose_text):
        errors.append("raw OPENAI_SAFETY_SALT environment entry is forbidden")
    if re.search(r"(?m)^\s*DATABASE_URL\s*:", compose_text):
        errors.append("raw DATABASE_URL environment entry is forbidden")
    if ":latest" in compose_text and "mutable latest reference is forbidden" not in errors:
        errors.append("mutable latest reference is forbidden")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--approved-lock", type=Path, default=DEFAULT_APPROVED_LOCK)
    args = parser.parse_args()
    try:
        compose, compose_text = load_yaml(args.compose)
        errors = validate_contract(
            compose,
            compose_text,
            load_json(args.lock),
            load_json(args.approved_lock),
        )
    except ContractError as exc:
        print(f"OpenAI provider runtime contract: FAIL: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"OpenAI provider runtime contract: FAIL: {error}", file=sys.stderr)
        return 1
    print("OpenAI provider runtime contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
