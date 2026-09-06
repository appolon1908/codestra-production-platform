#!/usr/bin/env python3
"""Apply additional fail-closed checks to the staging read-only manifest.

This validator is intentionally independent of deployment code. It reads only
the protected endpoint manifest, the committed source-lock file, and bounded
non-secret expectations supplied by the workflow. It never connects to a
server or prints manifest contents.
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
DEFAULT_SOURCE_LOCK = ROOT / "PRODUCTION-SOURCE-LOCK.yaml"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,191}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
IMAGE_RE = re.compile(
    r"^(?=.{1,255}$)"
    r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?"
    r"(?::[1-9][0-9]{0,4})?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+$"
)
ALLOWED_ROUTE_STATUSES = {200, 204, 401, 403}
SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}
ZERO_SHA = "0" * 40
ZERO_HASH = "0" * 64
ZERO_DIGEST = "sha256:" + ZERO_HASH


class HardeningError(ValueError):
    """A bounded validation failure that never includes secret material."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HardeningError(f"cannot load endpoint manifest: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise HardeningError("endpoint manifest must contain a JSON object")
    return value


def file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise HardeningError(f"cannot read source lock: {type(exc).__name__}") from exc


def validate_off_host_uri(value: object, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append("backups.off_host_uri must be a non-empty URI")
        return
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"s3", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        errors.append(
            "backups.off_host_uri must be credential-free s3 or HTTPS without query or fragment"
        )


def find_embedded_credentials(value: object, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            normalized = str(key).strip().lower()
            if (
                normalized in SENSITIVE_KEYS
                and not normalized.endswith("_ref")
                and child not in (None, "", False)
            ):
                errors.append(f"{child_path} must not embed credential material")
            find_embedded_credentials(child, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            find_embedded_credentials(child, f"{path}[{index}]", errors)
    elif isinstance(value, str):
        normalized = value.strip()
        if normalized.lower().startswith("bearer "):
            errors.append(f"{path} must not embed a bearer credential")
        if "-----BEGIN " in normalized and "PRIVATE KEY-----" in normalized:
            errors.append(f"{path} must not embed a private key")


def component_map(
    value: object,
    label: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list) or not value:
        errors.append(f"{label} must be a non-empty list")
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
        image_digest = item.get("image_digest")

        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            errors.append(f"{item_label}.name is invalid")
            continue
        if name in output:
            errors.append(f"{label} contains duplicate component {name}")
            continue
        output[name] = item

        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
            errors.append(f"{item_label}.repository must be owner/name")
        if (
            not isinstance(source_sha, str)
            or not SHA_RE.fullmatch(source_sha)
            or source_sha == ZERO_SHA
        ):
            errors.append(f"{item_label}.source_sha must be a non-zero exact SHA")
        if not isinstance(image, str) or not IMAGE_RE.fullmatch(image):
            errors.append(
                f"{item_label}.image must be a lowercase untagged registry repository"
            )
        if (
            not isinstance(image_digest, str)
            or not DIGEST_RE.fullmatch(image_digest)
            or image_digest == ZERO_DIGEST
        ):
            errors.append(f"{item_label}.image_digest must be a non-zero OCI digest")
        if item.get("rebuild_allowed") is not False:
            errors.append(f"{item_label}.rebuild_allowed must be false")
        if item.get("retag_allowed") is not False:
            errors.append(f"{item_label}.retag_allowed must be false")

    return output


def validate_routes(manifest: dict[str, Any], errors: list[str]) -> None:
    kong = manifest.get("kong")
    if not isinstance(kong, dict):
        errors.append("kong must be an object")
        return
    routes = kong.get("routes")
    if not isinstance(routes, list) or len(routes) != 29:
        errors.append("kong.routes must enumerate exactly 29 routes")
        return

    for index, route in enumerate(routes):
        label = f"kong.routes[{index}]"
        if not isinstance(route, dict):
            errors.append(f"{label} must be an object")
            continue
        if route.get("method") not in {"GET", "HEAD"}:
            errors.append(f"{label}.method must be GET or HEAD")
        statuses = route.get("expected_status")
        if (
            not isinstance(statuses, list)
            or not statuses
            or any(
                isinstance(status, bool)
                or not isinstance(status, int)
                or status not in ALLOWED_ROUTE_STATUSES
                for status in statuses
            )
        ):
            errors.append(
                f"{label}.expected_status may contain only 200, 204, 401, or 403"
            )
        elif len(statuses) != len(set(statuses)):
            errors.append(f"{label}.expected_status must not contain duplicates")


def validate_rollback(
    candidate: dict[str, Any],
    previous: dict[str, Any],
    current_components: dict[str, dict[str, Any]],
    previous_components: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    release_id = candidate.get("release_id")
    previous_release_id = previous.get("release_id")
    if (
        isinstance(release_id, str)
        and isinstance(previous_release_id, str)
        and release_id == previous_release_id
    ):
        errors.append("previous_candidate.release_id must differ from candidate.release_id")

    if not current_components or not previous_components:
        return
    if set(current_components) != set(previous_components):
        errors.append("candidate and previous_candidate component sets must match")
        return

    changed = False
    for name in sorted(current_components):
        current = current_components[name]
        old = previous_components[name]
        if current.get("repository") != old.get("repository"):
            errors.append(
                f"previous_candidate.components[{name}].repository must match candidate"
            )
        if current.get("image") != old.get("image"):
            errors.append(
                f"previous_candidate.components[{name}].image must match candidate"
            )
        if (
            current.get("source_sha") != old.get("source_sha")
            or current.get("image_digest") != old.get("image_digest")
        ):
            changed = True

    if not changed:
        errors.append(
            "previous_candidate must differ by at least one source SHA or image digest"
        )


def validate_manifest(
    manifest: dict[str, Any],
    *,
    source_lock_path: Path,
    expected_platform_sha: str | None,
    expected_off_host_uri: str | None,
) -> tuple[list[str], str | None]:
    errors: list[str] = []

    if manifest.get("template") is not False:
        errors.append("materialized endpoint manifest must set template=false")

    find_embedded_credentials(manifest, "", errors)

    candidate = manifest.get("candidate")
    previous = manifest.get("previous_candidate")
    if not isinstance(candidate, dict):
        errors.append("candidate must be an object")
        candidate = {}
    if not isinstance(previous, dict):
        errors.append("previous_candidate must be an object")
        previous = {}

    platform_sha = candidate.get("platform_source_sha")
    if (
        not isinstance(platform_sha, str)
        or not SHA_RE.fullmatch(platform_sha)
        or platform_sha == ZERO_SHA
    ):
        errors.append("candidate.platform_source_sha must be a non-zero exact SHA")
    if expected_platform_sha:
        if not SHA_RE.fullmatch(expected_platform_sha):
            errors.append("workflow expected platform SHA is invalid")
        elif platform_sha != expected_platform_sha:
            errors.append(
                "candidate.platform_source_sha does not match the protected workflow SHA"
            )

    source_lock_hash: str | None = None
    try:
        source_lock_hash = file_sha256(source_lock_path)
    except HardeningError as exc:
        errors.append(str(exc))
    declared_source_lock_hash = candidate.get("source_lock_sha256")
    if (
        not isinstance(declared_source_lock_hash, str)
        or not HASH_RE.fullmatch(declared_source_lock_hash)
        or declared_source_lock_hash == ZERO_HASH
    ):
        errors.append("candidate.source_lock_sha256 must be a non-zero SHA-256")
    elif source_lock_hash and declared_source_lock_hash != source_lock_hash:
        errors.append(
            "candidate.source_lock_sha256 does not match PRODUCTION-SOURCE-LOCK.yaml"
        )

    current_components = component_map(
        candidate.get("components"),
        "candidate.components",
        errors,
    )
    previous_components = component_map(
        previous.get("components"),
        "previous_candidate.components",
        errors,
    )
    validate_rollback(
        candidate,
        previous,
        current_components,
        previous_components,
        errors,
    )
    validate_routes(manifest, errors)

    backups = manifest.get("backups")
    if not isinstance(backups, dict):
        errors.append("backups must be an object")
    else:
        off_host_uri = backups.get("off_host_uri")
        validate_off_host_uri(off_host_uri, errors)
        if expected_off_host_uri and off_host_uri != expected_off_host_uri:
            errors.append(
                "backups.off_host_uri does not match the protected environment variable"
            )

    return sorted(set(errors)), source_lock_hash


def write_evidence(
    path: Path | None,
    *,
    errors: list[str],
    source_lock_hash: str | None,
    expected_platform_sha: str | None,
    expected_off_host_uri: str | None,
) -> None:
    if path is None:
        return
    evidence = {
        "schema_version": 1,
        "mode": "manifest-hardening",
        "status": "PASS" if not errors else "BLOCKED",
        "production_changed": False,
        "runtime_contacted": False,
        "ssh_attempted": False,
        "secret_values_recorded": False,
        "source_lock_sha256": source_lock_hash,
        "protected_platform_sha_checked": bool(expected_platform_sha),
        "off_host_uri_binding_checked": bool(expected_off_host_uri),
        "blockers": errors,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint-manifest", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, default=DEFAULT_SOURCE_LOCK)
    parser.add_argument("--expected-platform-sha")
    parser.add_argument("--expected-off-host-uri")
    parser.add_argument("--evidence-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    expected_platform_sha = (
        args.expected_platform_sha
        or os.environ.get("EXPECTED_SHA", "").strip()
        or os.environ.get("GITHUB_SHA", "").strip()
        or None
    )
    expected_off_host_uri = (
        args.expected_off_host_uri
        or os.environ.get("CODESTRA_STAGING_OFF_HOST_BACKUP_URI", "").strip()
        or None
    )

    errors: list[str]
    source_lock_hash: str | None = None
    try:
        manifest = load_json(args.endpoint_manifest)
        errors, source_lock_hash = validate_manifest(
            manifest,
            source_lock_path=args.source_lock,
            expected_platform_sha=expected_platform_sha,
            expected_off_host_uri=expected_off_host_uri,
        )
    except HardeningError as exc:
        errors = [str(exc)]

    write_evidence(
        args.evidence_output,
        errors=errors,
        source_lock_hash=source_lock_hash,
        expected_platform_sha=expected_platform_sha,
        expected_off_host_uri=expected_off_host_uri,
    )

    if errors:
        for error in errors:
            print(f"STAGING_READONLY_HARDENING_BLOCKER={error}", file=sys.stderr)
        print("STAGING_READONLY_HARDENING=BLOCKED")
        return 1

    print("STAGING_READONLY_HARDENING=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
