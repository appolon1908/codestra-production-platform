#!/usr/bin/env python3
"""Validate a signed Middleware release artifact and derive canonical evidence.

The upstream release artifact contains a canonical signed manifest, a Sigstore
bundle, an SPDX SBOM, and a Grype JSON report. This module verifies those exact
files and derives deterministic provenance and OpenVEX records for the platform
release tuple without pretending that the upstream artifact shipped legacy
RELEASE.env, CycloneDX, or OpenVEX files.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_FILES = {
    "middleware.grype.json",
    "middleware.spdx.json",
    "release-manifest.v1.json",
    "release-manifest.v1.sigstore.json",
}
BUNDLE_MEDIA_TYPE = "application/vnd.dev.sigstore.bundle.v0.3+json"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"


class SignedReleaseError(RuntimeError):
    """The signed release artifact is incomplete, inconsistent, or untrusted."""


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise SignedReleaseError(f"release evidence is not a regular file: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SignedReleaseError(f"{label} must be an object")
    return value


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    result = _require_object(value, label)
    if set(result) != expected:
        raise SignedReleaseError(f"{label} fields are not exact")
    return result


def _require_constant(value: object, expected: object, label: str) -> None:
    if value != expected:
        raise SignedReleaseError(f"{label} is not canonical")


def _load_canonical_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SignedReleaseError(f"{label} cannot be loaded") from exc
    result = _require_object(value, label)
    if raw != canonical_json(result):
        raise SignedReleaseError(f"{label} is not canonical JSON")
    return result, raw


def _validate_bundle_structure(bundle_path: Path, manifest_raw: bytes) -> dict[str, Any]:
    try:
        bundle = json.loads(bundle_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SignedReleaseError("Sigstore bundle cannot be loaded") from exc
    bundle = _require_exact_keys(
        bundle,
        {"mediaType", "messageSignature", "verificationMaterial"},
        "Sigstore bundle",
    )
    _require_constant(bundle["mediaType"], BUNDLE_MEDIA_TYPE, "Sigstore bundle media type")
    message = _require_exact_keys(
        bundle["messageSignature"], {"messageDigest", "signature"}, "message signature"
    )
    digest = _require_exact_keys(
        message["messageDigest"], {"algorithm", "digest"}, "message digest"
    )
    _require_constant(digest["algorithm"], "SHA2_256", "message digest algorithm")
    try:
        decoded_digest = base64.b64decode(digest["digest"], validate=True)
        signature = base64.b64decode(message["signature"], validate=True)
    except (TypeError, ValueError) as exc:
        raise SignedReleaseError("Sigstore signature material is not valid base64") from exc
    if decoded_digest != hashlib.sha256(manifest_raw).digest():
        raise SignedReleaseError("Sigstore bundle message digest differs from manifest")
    if not signature:
        raise SignedReleaseError("Sigstore bundle signature is empty")

    material = _require_exact_keys(
        bundle["verificationMaterial"],
        {"certificate", "timestampVerificationData", "tlogEntries"},
        "verification material",
    )
    certificate = _require_exact_keys(material["certificate"], {"rawBytes"}, "certificate")
    try:
        raw_certificate = base64.b64decode(certificate["rawBytes"], validate=True)
    except (TypeError, ValueError) as exc:
        raise SignedReleaseError("Sigstore certificate is not valid base64") from exc
    if not raw_certificate:
        raise SignedReleaseError("Sigstore certificate is empty")
    entries = material["tlogEntries"]
    if not isinstance(entries, list) or not entries:
        raise SignedReleaseError("Sigstore transparency-log entry is missing")
    for entry in entries:
        entry = _require_object(entry, "transparency-log entry")
        if not entry.get("canonicalizedBody") or not entry.get("logId"):
            raise SignedReleaseError("Sigstore transparency-log entry is incomplete")
        promise = _require_object(entry.get("inclusionPromise"), "inclusion promise")
        proof = _require_object(entry.get("inclusionProof"), "inclusion proof")
        if not promise.get("signedEntryTimestamp"):
            raise SignedReleaseError("Sigstore inclusion promise is empty")
        if not proof.get("rootHash") or not isinstance(proof.get("hashes"), list):
            raise SignedReleaseError("Sigstore inclusion proof is incomplete")
    return bundle


def verify_sigstore_bundle(
    manifest_path: Path,
    bundle_path: Path,
    *,
    certificate_identity: str,
    cosign: str,
) -> None:
    command = [
        cosign,
        "verify-blob",
        str(manifest_path),
        "--bundle",
        str(bundle_path),
        "--certificate-identity",
        certificate_identity,
        "--certificate-oidc-issuer",
        OIDC_ISSUER,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SignedReleaseError("Sigstore manifest verification could not run") from exc
    if completed.returncode != 0:
        raise SignedReleaseError("Sigstore manifest verification failed")


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    expected_repository: str,
    expected_image_repository: str,
    expected_workflow_identity: str,
    expected_source_sha: str,
    expected_image_digest: str,
    expected_run_id: str,
) -> None:
    root = _require_exact_keys(
        manifest,
        {
            "schema_version",
            "release_id",
            "service",
            "repository",
            "source",
            "image",
            "runtime",
            "build",
            "artifacts",
            "verification",
            "promotion",
        },
        "release manifest",
    )
    _require_constant(root["schema_version"], "1.0", "manifest schema version")
    _require_constant(root["service"], "middleware-api", "manifest service")
    _require_constant(root["repository"], expected_repository, "manifest repository")

    source = _require_exact_keys(root["source"], {"git_sha", "git_tree_id", "ref"}, "source")
    if source["git_sha"] != expected_source_sha or SHA40_RE.fullmatch(source["git_sha"]) is None:
        raise SignedReleaseError("manifest source SHA differs from exact authority")
    if not isinstance(source["git_tree_id"], str) or SHA40_RE.fullmatch(source["git_tree_id"]) is None:
        raise SignedReleaseError("manifest Git tree identity is invalid")
    _require_constant(source["ref"], "refs/heads/main", "manifest source ref")

    image = _require_exact_keys(
        root["image"],
        {"repository", "digest", "reference", "platforms", "base_image"},
        "image",
    )
    _require_constant(image["repository"], expected_image_repository, "image repository")
    if image["digest"] != expected_image_digest or DIGEST_RE.fullmatch(image["digest"]) is None:
        raise SignedReleaseError("manifest image digest differs from exact authority")
    _require_constant(
        image["reference"],
        f"{expected_image_repository}@{expected_image_digest}",
        "image reference",
    )
    _require_constant(image["platforms"], ["linux/amd64"], "image platforms")
    if not isinstance(image["base_image"], str) or "@sha256:" not in image["base_image"]:
        raise SignedReleaseError("base image is not immutable")
    _require_constant(
        root["release_id"],
        f"{expected_source_sha[:12]}-{expected_image_digest[7:19]}",
        "release identity",
    )

    runtime = _require_exact_keys(
        root["runtime"],
        {"schema_or_migration_head", "runtime_profile_ids", "external_effects_default"},
        "runtime",
    )
    if runtime["schema_or_migration_head"] != "0056_klyrow_delivery_events":
        raise SignedReleaseError("manifest migration head is not the certified candidate head")
    _require_constant(
        runtime["runtime_profile_ids"],
        [
            "codestra-middleware-production-compose-v1",
            "codestra-middleware-production-v1",
            "codestra-middleware-staging-v1",
        ],
        "runtime profiles",
    )
    _require_constant(runtime["external_effects_default"], "disabled", "external effects")

    build = _require_exact_keys(
        root["build"],
        {
            "workflow_path",
            "workflow_identity",
            "run_id",
            "run_attempt",
            "built_at",
            "runner_image",
            "provenance",
        },
        "build",
    )
    _require_constant(build["workflow_path"], ".github/workflows/release.yml", "workflow path")
    _require_constant(build["workflow_identity"], expected_workflow_identity, "workflow identity")
    if str(build["run_id"]) != str(expected_run_id):
        raise SignedReleaseError("manifest run ID differs from exact release run")
    if type(build["run_attempt"]) is not int or build["run_attempt"] < 1:
        raise SignedReleaseError("manifest run attempt is invalid")
    _require_constant(build["runner_image"], "ubuntu-24.04", "runner image")
    _require_constant(build["provenance"], "buildkit-mode-max", "provenance mode")

    artifacts = _require_object(root["artifacts"], "artifacts")
    required_artifacts = {
        "contracts_bundle",
        "dependency_input",
        "dependency_lock",
        "dockerfile",
        "migrations_bundle",
        "runtime_profiles",
        "sbom",
        "test_dependency_input",
        "test_dependency_lock",
        "vulnerability_report",
    }
    if set(artifacts) != required_artifacts:
        raise SignedReleaseError("manifest artifact inventory is not exact")
    for key, entry in artifacts.items():
        entry = _require_exact_keys(entry, {"path", "sha256"}, f"artifact {key}")
        if not isinstance(entry["path"], str) or not entry["path"]:
            raise SignedReleaseError(f"artifact {key} path is invalid")
        if not isinstance(entry["sha256"], str) or DIGEST_RE.fullmatch(entry["sha256"]) is None:
            raise SignedReleaseError(f"artifact {key} digest is invalid")
    _require_constant(artifacts["sbom"]["path"], "middleware.spdx.json", "SBOM path")
    _require_constant(
        artifacts["vulnerability_report"]["path"],
        "middleware.grype.json",
        "vulnerability report path",
    )

    verification = _require_exact_keys(
        root["verification"],
        {
            "image_signature",
            "manifest_signature",
            "oidc_issuer",
            "certificate_identity",
            "transparency_log_required",
            "vulnerability_policy",
        },
        "verification",
    )
    _require_constant(verification["image_signature"], "sigstore-keyless", "image signature")
    _require_constant(
        verification["manifest_signature"],
        "sigstore-keyless-bundle",
        "manifest signature",
    )
    _require_constant(verification["oidc_issuer"], OIDC_ISSUER, "OIDC issuer")
    _require_constant(
        verification["certificate_identity"], expected_workflow_identity, "certificate identity"
    )
    _require_constant(verification["transparency_log_required"], True, "transparency log")
    _require_constant(
        verification["vulnerability_policy"],
        "fail-high-or-critical-with-fix",
        "vulnerability policy",
    )
    promotion = _require_exact_keys(
        root["promotion"],
        {"staging_and_production_same_digest", "mutable_tags_authoritative"},
        "promotion",
    )
    _require_constant(promotion["staging_and_production_same_digest"], True, "same digest")
    _require_constant(promotion["mutable_tags_authoritative"], False, "mutable tags")


def _validate_grype(value: object) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report = _require_object(value, "Grype report")
    matches = report.get("matches")
    if not isinstance(matches, list):
        raise SignedReleaseError("Grype report matches are missing")
    statements: list[dict[str, Any]] = []
    for match in matches:
        item = _require_object(match, "Grype match")
        vulnerability = _require_object(item.get("vulnerability"), "Grype vulnerability")
        identifier = vulnerability.get("id")
        severity = str(vulnerability.get("severity", "unknown")).lower()
        fix = vulnerability.get("fix") or {}
        versions = fix.get("versions") if isinstance(fix, dict) else []
        if severity in {"high", "critical"} and isinstance(versions, list) and versions:
            raise SignedReleaseError("Grype report contains a fixable high or critical finding")
        if isinstance(identifier, str) and identifier:
            statements.append(
                {
                    "vulnerability": {"name": identifier},
                    "status": "affected",
                    "impact_statement": f"Reported by Grype with severity {severity}.",
                }
            )
    return report, statements


def _derived_provenance(
    manifest: dict[str, Any],
    *,
    artifact_name: str,
    artifact_digest: str,
    manifest_sha256: str,
    bundle_sha256: str,
    sbom_sha256: str,
    vulnerability_report_sha256: str,
) -> dict[str, Any]:
    digest = manifest["image"]["digest"].removeprefix("sha256:")
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://slsa.dev/provenance/v1",
        "subject": [
            {"name": manifest["image"]["repository"], "digest": {"sha256": digest}}
        ],
        "predicate": {
            "buildDefinition": {
                "buildType": "https://github.com/Attestations/GitHubActionsWorkflow@v1",
                "externalParameters": {
                    "repository": manifest["repository"],
                    "sourceSha": manifest["source"]["git_sha"],
                    "sourceRef": manifest["source"]["ref"],
                    "workflowIdentity": manifest["build"]["workflow_identity"],
                    "runId": manifest["build"]["run_id"],
                    "runAttempt": manifest["build"]["run_attempt"],
                },
                "internalParameters": {
                    "releaseArtifact": artifact_name,
                    "releaseArtifactDigest": artifact_digest,
                    "releaseManifestSha256": manifest_sha256,
                    "sigstoreBundleSha256": bundle_sha256,
                    "sbomSha256": sbom_sha256,
                    "vulnerabilityReportSha256": vulnerability_report_sha256,
                },
                "resolvedDependencies": [
                    {
                        "uri": (
                            f"git+https://github.com/{manifest['repository']}@"
                            f"{manifest['source']['git_sha']}"
                        ),
                        "digest": {"gitTree": manifest["source"]["git_tree_id"]},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": manifest["build"]["workflow_identity"]},
                "metadata": {
                    "invocationId": (
                        f"https://github.com/{manifest['repository']}/actions/runs/"
                        f"{manifest['build']['run_id']}/attempts/"
                        f"{manifest['build']['run_attempt']}"
                    ),
                    "startedOn": manifest["build"]["built_at"],
                    "finishedOn": manifest["build"]["built_at"],
                },
            },
        },
    }


def _derived_openvex(
    manifest: dict[str, Any],
    statements: list[dict[str, Any]],
    *,
    vulnerability_report_sha256: str,
) -> dict[str, Any]:
    image_reference = manifest["image"]["reference"]
    completed = []
    for statement in statements:
        value = dict(statement)
        value["products"] = [{"@id": image_reference}]
        completed.append(value)
    return {
        "@context": "https://openvex.dev/ns/v0.2.0",
        "@id": (
            "https://github.com/appolon1908-hue/codestra-production-platform/"
            f"security/openvex/{manifest['release_id']}"
        ),
        "author": "Codestra production release authority",
        "timestamp": manifest["build"]["built_at"],
        "version": 1,
        "tooling": "codestra-production-platform/tools/signed_middleware_release.py",
        "statements": completed,
        "metadata": {
            "source_sha": manifest["source"]["git_sha"],
            "image_digest": manifest["image"]["digest"],
            "derived_from": "middleware.grype.json",
            "vulnerability_report_sha256": vulnerability_report_sha256,
            "grype_match_count": len(completed),
        },
    }


def validate_signed_release(
    directory: Path,
    *,
    expected_repository: str,
    expected_image_repository: str,
    expected_workflow_identity: str,
    expected_source_sha: str,
    expected_image_digest: str,
    expected_run_id: str,
    artifact_name: str,
    artifact_digest: str,
    cosign: str = "cosign",
    verify_signature: bool = True,
) -> dict[str, Any]:
    directory = directory.resolve()
    files = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }
    if files != EXPECTED_FILES:
        raise SignedReleaseError(
            "signed release file inventory differs: "
            f"expected={sorted(EXPECTED_FILES)!r} actual={sorted(files)!r}"
        )
    if not artifact_name.startswith(
        f"signed-middleware-release-{expected_source_sha}-{expected_run_id}-"
    ):
        raise SignedReleaseError("signed release artifact name differs from exact run")
    if DIGEST_RE.fullmatch(artifact_digest) is None:
        raise SignedReleaseError("signed release artifact digest is invalid")

    manifest_path = directory / "release-manifest.v1.json"
    bundle_path = directory / "release-manifest.v1.sigstore.json"
    manifest, manifest_raw = _load_canonical_json(manifest_path, "release manifest")
    _validate_manifest(
        manifest,
        expected_repository=expected_repository,
        expected_image_repository=expected_image_repository,
        expected_workflow_identity=expected_workflow_identity,
        expected_source_sha=expected_source_sha,
        expected_image_digest=expected_image_digest,
        expected_run_id=expected_run_id,
    )
    _validate_bundle_structure(bundle_path, manifest_raw)
    if verify_signature:
        verify_sigstore_bundle(
            manifest_path,
            bundle_path,
            certificate_identity=expected_workflow_identity,
            cosign=cosign,
        )

    sbom_path = directory / "middleware.spdx.json"
    grype_path = directory / "middleware.grype.json"
    sbom_sha256 = sha256_file(sbom_path)
    vulnerability_report_sha256 = sha256_file(grype_path)
    if manifest["artifacts"]["sbom"]["sha256"] != f"sha256:{sbom_sha256}":
        raise SignedReleaseError("SPDX SBOM digest differs from signed manifest")
    if manifest["artifacts"]["vulnerability_report"]["sha256"] != (
        f"sha256:{vulnerability_report_sha256}"
    ):
        raise SignedReleaseError("Grype report digest differs from signed manifest")
    try:
        grype = json.loads(grype_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SignedReleaseError("Grype report cannot be loaded") from exc
    _, vulnerability_statements = _validate_grype(grype)

    manifest_sha256 = sha256_bytes(manifest_raw)
    bundle_sha256 = sha256_file(bundle_path)
    provenance = _derived_provenance(
        manifest,
        artifact_name=artifact_name,
        artifact_digest=artifact_digest,
        manifest_sha256=manifest_sha256,
        bundle_sha256=bundle_sha256,
        sbom_sha256=sbom_sha256,
        vulnerability_report_sha256=vulnerability_report_sha256,
    )
    openvex = _derived_openvex(
        manifest,
        vulnerability_statements,
        vulnerability_report_sha256=vulnerability_report_sha256,
    )
    provenance_bytes = canonical_json(provenance)
    openvex_bytes = canonical_json(openvex)
    return {
        "source_sha": manifest["source"]["git_sha"],
        "git_tree_id": manifest["source"]["git_tree_id"],
        "image_digest": manifest["image"]["digest"],
        "image_reference": manifest["image"]["reference"],
        "builder": manifest["build"]["workflow_identity"],
        "migration_head": manifest["runtime"]["schema_or_migration_head"],
        "release_id": manifest["release_id"],
        "artifact": artifact_name,
        "artifact_digest": artifact_digest,
        "run_id": str(manifest["build"]["run_id"]),
        "sbom_sha256": sbom_sha256,
        "vulnerability_report_sha256": vulnerability_report_sha256,
        "release_manifest_sha256": manifest_sha256,
        "sigstore_bundle_sha256": bundle_sha256,
        "provenance_sha256": sha256_bytes(provenance_bytes),
        "openvex_sha256": sha256_bytes(openvex_bytes),
        "provenance": provenance,
        "openvex": openvex,
    }
