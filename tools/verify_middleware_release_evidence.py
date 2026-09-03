#!/usr/bin/env python3
"""Validate the exact signed Appolon Middleware release before platform binding."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


REPOSITORY = "appolon1908-hue/Middleware-"
IMAGE_REPOSITORY = "ghcr.io/appolon1908-hue/codestra-middleware"
SOURCE_REF = "refs/heads/main"
WORKFLOW_IDENTITY = (
    "https://github.com/appolon1908-hue/Middleware-/"
    ".github/workflows/release.yml@refs/heads/main"
)
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
SERVICE = "middleware-api"
SCHEMA_VERSION = "1.0"
EXPECTED_FILES = {
    "release-manifest.v1.json",
    "release-manifest.v1.sigstore.json",
    "middleware.spdx.json",
    "middleware.grype.json",
}
TUPLE_FIELDS = {
    "schema_version",
    "change_id",
    "release_version",
    "middleware_repository",
    "middleware_source_sha",
    "middleware_source_tree",
    "middleware_image_repository",
    "middleware_digest",
    "middleware_migration_head",
    "middleware_run_id",
    "middleware_run_attempt",
    "middleware_artifact_id",
    "middleware_artifact",
    "middleware_artifact_zip_sha256",
    "middleware_release_manifest_sha256",
    "middleware_sigstore_bundle_sha256",
    "middleware_sbom_sha256",
    "middleware_vulnerability_report_sha256",
    "middleware_workflow_identity",
    "middleware_oidc_issuer",
    "middleware_external_effects_default",
    "same_digest_promotion_required",
    "production_deployment_authorized",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
HASH64 = re.compile(r"^[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
MIGRATION = re.compile(r"^[0-9]{4}_[a-z0-9_]+$")


class EvidenceError(ValueError):
    """The supplied release evidence is missing, malformed, or inconsistent."""


def sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise EvidenceError(f"release evidence must be a regular file: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"cannot load {path.name}: {type(error).__name__}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"{path.name} must contain an object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def validate_tuple(authority: dict[str, Any]) -> None:
    require(set(authority) == TUPLE_FIELDS, "protected release tuple fields are not exact")
    require(
        authority["schema_version"] == "codestra.production-release-tuple.v2",
        "protected release tuple schema is not v2",
    )
    require(authority["middleware_repository"] == REPOSITORY, "middleware repository is unauthorized")
    require(
        authority["middleware_image_repository"] == IMAGE_REPOSITORY,
        "middleware image repository is unauthorized",
    )
    require(
        isinstance(authority["middleware_source_sha"], str)
        and SHA40.fullmatch(authority["middleware_source_sha"]) is not None,
        "middleware source SHA is invalid",
    )
    require(
        isinstance(authority["middleware_source_tree"], str)
        and SHA40.fullmatch(authority["middleware_source_tree"]) is not None,
        "middleware source tree is invalid",
    )
    require(
        isinstance(authority["middleware_digest"], str)
        and DIGEST.fullmatch(authority["middleware_digest"]) is not None,
        "middleware image digest is invalid",
    )
    require(
        isinstance(authority["middleware_migration_head"], str)
        and MIGRATION.fullmatch(authority["middleware_migration_head"]) is not None,
        "middleware migration head is invalid",
    )
    require(
        isinstance(authority["middleware_run_id"], str)
        and authority["middleware_run_id"].isdigit()
        and int(authority["middleware_run_id"]) > 0,
        "middleware run ID is invalid",
    )
    require(
        type(authority["middleware_run_attempt"]) is int
        and authority["middleware_run_attempt"] > 0,
        "middleware run attempt is invalid",
    )
    require(
        type(authority["middleware_artifact_id"]) is int
        and authority["middleware_artifact_id"] > 0,
        "middleware artifact ID is invalid",
    )
    expected_artifact = (
        f"signed-middleware-release-{authority['middleware_source_sha']}-"
        f"{authority['middleware_run_id']}-{authority['middleware_run_attempt']}"
    )
    require(
        authority["middleware_artifact"] == expected_artifact,
        "middleware artifact name is not bound to source and run",
    )
    for field in (
        "middleware_artifact_zip_sha256",
        "middleware_release_manifest_sha256",
        "middleware_sigstore_bundle_sha256",
        "middleware_sbom_sha256",
        "middleware_vulnerability_report_sha256",
    ):
        require(
            isinstance(authority[field], str) and HASH64.fullmatch(authority[field]) is not None,
            f"{field} is not an exact SHA-256",
        )
    require(
        authority["middleware_workflow_identity"] == WORKFLOW_IDENTITY,
        "middleware workflow identity is unauthorized",
    )
    require(
        authority["middleware_oidc_issuer"] == OIDC_ISSUER,
        "middleware OIDC issuer is unauthorized",
    )
    require(
        authority["middleware_external_effects_default"] == "disabled",
        "middleware external effects must default to disabled",
    )
    require(
        authority["same_digest_promotion_required"] is True,
        "staging and production must use the same digest",
    )
    require(
        authority["production_deployment_authorized"] is False,
        "source authority must not self-authorize production deployment",
    )


def validate(
    directory: Path,
    tuple_path: Path,
) -> dict[str, str]:
    directory = directory.resolve()
    require(directory.is_dir(), "middleware release evidence directory is missing")
    names = {item.name for item in directory.iterdir()}
    require(names == EXPECTED_FILES, "middleware release evidence file set is not exact")
    for item in directory.iterdir():
        require(item.is_file() and not item.is_symlink(), "middleware evidence contains a non-regular file")

    authority = load_json(tuple_path)
    validate_tuple(authority)

    paths = {name: directory / name for name in EXPECTED_FILES}
    expected_hashes = {
        "release-manifest.v1.json": authority["middleware_release_manifest_sha256"],
        "release-manifest.v1.sigstore.json": authority["middleware_sigstore_bundle_sha256"],
        "middleware.spdx.json": authority["middleware_sbom_sha256"],
        "middleware.grype.json": authority["middleware_vulnerability_report_sha256"],
    }
    for name, expected in expected_hashes.items():
        require(sha256(paths[name]) == expected, f"{name} SHA-256 differs from protected tuple")

    manifest = load_json(paths["release-manifest.v1.json"])
    require(manifest.get("schema_version") == SCHEMA_VERSION, "middleware manifest schema mismatch")
    require(manifest.get("service") == SERVICE, "middleware service identity mismatch")
    require(manifest.get("repository") == REPOSITORY, "middleware manifest repository mismatch")

    source = manifest.get("source")
    require(isinstance(source, dict), "middleware manifest source is missing")
    require(source.get("git_sha") == authority["middleware_source_sha"], "middleware source SHA differs")
    require(source.get("git_tree_id") == authority["middleware_source_tree"], "middleware source tree differs")
    require(source.get("ref") == SOURCE_REF, "middleware source ref is unauthorized")

    image = manifest.get("image")
    require(isinstance(image, dict), "middleware manifest image is missing")
    require(image.get("repository") == IMAGE_REPOSITORY, "middleware manifest image repository differs")
    require(image.get("digest") == authority["middleware_digest"], "middleware manifest image digest differs")
    expected_reference = f"{IMAGE_REPOSITORY}@{authority['middleware_digest']}"
    require(image.get("reference") == expected_reference, "middleware manifest image reference differs")
    require(image.get("platforms") == ["linux/amd64"], "middleware platform set differs")

    runtime = manifest.get("runtime")
    require(isinstance(runtime, dict), "middleware runtime metadata is missing")
    require(
        runtime.get("schema_or_migration_head") == authority["middleware_migration_head"],
        "middleware migration head differs",
    )
    require(runtime.get("external_effects_default") == "disabled", "middleware effects are not fail closed")

    build = manifest.get("build")
    require(isinstance(build, dict), "middleware build metadata is missing")
    require(str(build.get("run_id")) == authority["middleware_run_id"], "middleware run ID differs")
    require(
        build.get("run_attempt") == authority["middleware_run_attempt"],
        "middleware run attempt differs",
    )
    require(build.get("workflow_identity") == WORKFLOW_IDENTITY, "middleware build identity differs")
    require(build.get("provenance") == "buildkit-mode-max", "middleware provenance mode differs")

    verification = manifest.get("verification")
    require(isinstance(verification, dict), "middleware verification metadata is missing")
    require(
        verification.get("certificate_identity") == WORKFLOW_IDENTITY,
        "middleware certificate identity differs",
    )
    require(verification.get("oidc_issuer") == OIDC_ISSUER, "middleware OIDC issuer differs")
    require(verification.get("transparency_log_required") is True, "transparency log is not required")

    promotion = manifest.get("promotion")
    require(isinstance(promotion, dict), "middleware promotion metadata is missing")
    require(
        promotion.get("staging_and_production_same_digest") is True,
        "middleware same-digest promotion is not required",
    )
    require(promotion.get("mutable_tags_authoritative") is False, "mutable tags are authoritative")

    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, dict), "middleware artifact bindings are missing")
    require(
        artifacts.get("sbom", {}).get("sha256")
        == "sha256:" + authority["middleware_sbom_sha256"],
        "middleware manifest SBOM binding differs",
    )
    require(
        artifacts.get("vulnerability_report", {}).get("sha256")
        == "sha256:" + authority["middleware_vulnerability_report_sha256"],
        "middleware vulnerability-report binding differs",
    )

    bundle = load_json(paths["release-manifest.v1.sigstore.json"])
    require(
        bundle.get("mediaType") == "application/vnd.dev.sigstore.bundle.v0.3+json",
        "middleware Sigstore bundle media type differs",
    )
    require(isinstance(bundle.get("messageSignature"), dict), "middleware bundle signature is missing")
    material = bundle.get("verificationMaterial")
    require(isinstance(material, dict), "middleware verification material is missing")
    require(bool(material.get("certificate")), "middleware signing certificate is missing")
    require(bool(material.get("tlogEntries")), "middleware transparency-log entry is missing")

    sbom = load_json(paths["middleware.spdx.json"])
    require(sbom.get("spdxVersion") == "SPDX-2.3", "middleware SBOM is not SPDX 2.3")
    require(sbom.get("name") == IMAGE_REPOSITORY, "middleware SBOM image name differs")
    require(isinstance(sbom.get("packages"), list) and bool(sbom["packages"]), "middleware SBOM is empty")
    require(
        authority["middleware_digest"] in json.dumps(sbom, sort_keys=True),
        "middleware SBOM does not bind the selected digest",
    )

    vulnerability = load_json(paths["middleware.grype.json"])
    require(vulnerability.get("descriptor", {}).get("name") == "grype", "middleware scanner identity differs")
    require(vulnerability.get("source", {}).get("type") == "image", "middleware scan source is not an image")
    target = (
        vulnerability.get("source", {})
        .get("target", {})
        .get("userInput", "")
    )
    require(IMAGE_REPOSITORY in target, "middleware scan image repository differs")
    require(
        authority["middleware_digest"].removeprefix("sha256:") in target,
        "middleware scan digest differs",
    )
    require(vulnerability.get("matches") == [], "middleware vulnerability gate has findings")

    return {
        "MIDDLEWARE_PROTECTED_SHA": authority["middleware_source_sha"],
        "MIDDLEWARE_SOURCE_TREE": authority["middleware_source_tree"],
        "MIDDLEWARE_IMAGE_REPOSITORY": authority["middleware_image_repository"],
        "MIDDLEWARE_IMAGE_DIGEST": authority["middleware_digest"],
        "MIDDLEWARE_IMAGE_REFERENCE": expected_reference,
        "MIDDLEWARE_MIGRATION_HEAD": authority["middleware_migration_head"],
        "MIDDLEWARE_RELEASE_MANIFEST_SHA256": authority["middleware_release_manifest_sha256"],
        "MIDDLEWARE_SIGSTORE_BUNDLE_SHA256": authority["middleware_sigstore_bundle_sha256"],
        "MIDDLEWARE_SBOM_SHA256": authority["middleware_sbom_sha256"],
        "MIDDLEWARE_VULNERABILITY_REPORT_SHA256": authority[
            "middleware_vulnerability_report_sha256"
        ],
        "MIDDLEWARE_WORKFLOW_IDENTITY": authority["middleware_workflow_identity"],
        "MIDDLEWARE_OIDC_ISSUER": authority["middleware_oidc_issuer"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    parser.add_argument("--tuple", type=Path, required=True)
    args = parser.parse_args()
    values = validate(args.directory, args.tuple)
    with args.github_env.open("a", encoding="utf-8") as target:
        for key, value in values.items():
            target.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
