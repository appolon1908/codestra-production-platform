#!/usr/bin/env python3
"""Validate canonical Middleware production evidence before tuple binding.

The verifier accepts the historical RELEASE.env evidence contract for rollback
fixtures and the current signed v1 manifest contract. The current contract is
cryptographically verified with Cosign and derives deterministic provenance and
OpenVEX records from the signed manifest, SPDX SBOM, and Grype report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from signed_middleware_release import canonical_json, validate_signed_release  # noqa: E402

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
STAGING_ONLY_DIGEST = (
    "sha256:2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff"
)
CANONICAL_REPOSITORY = "Codestra-SRL/codestra-middleware"
CANONICAL_IMAGE = "ghcr.io/codestra-srl/codestra-middleware"
CANONICAL_WORKFLOW = ".github/workflows/exact-main-production-release.yml"
CANONICAL_BUILDER = (
    f"https://github.com/{CANONICAL_REPOSITORY}/{CANONICAL_WORKFLOW}@refs/heads/main"
)


def release_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise ValueError("middleware RELEASE.env is malformed")
        values[key] = value
    required = {"SOURCE_SHA", "IMAGE_REFERENCE", "IMAGE_DIGEST", "SBOM_SHA256"}
    if values.keys() != required:
        raise ValueError("middleware RELEASE.env fields are not exact")
    if not SHA_RE.fullmatch(values["SOURCE_SHA"]):
        raise ValueError("middleware source SHA is invalid")
    if not DIGEST_RE.fullmatch(values["IMAGE_DIGEST"]):
        raise ValueError("middleware image digest is invalid")
    if values["IMAGE_DIGEST"] == STAGING_ONLY_DIGEST:
        raise ValueError("staging-only middleware digest is prohibited")
    expected_reference = CANONICAL_IMAGE + "@" + values["IMAGE_DIGEST"]
    if values["IMAGE_REFERENCE"] != expected_reference:
        raise ValueError("middleware image reference and digest differ")
    return values


def _verify_tuple(
    tuple_path: Path,
    values: dict[str, str],
    *,
    run_id: str | None,
    artifact: str | None,
) -> None:
    authority = json.loads(tuple_path.read_text(encoding="utf-8"))
    required = {
        "change_id",
        "middleware_artifact",
        "middleware_digest",
        "middleware_openvex_sha256",
        "middleware_provenance_sha256",
        "middleware_run_id",
        "middleware_sbom_sha256",
        "middleware_source_sha",
        "release_version",
    }
    if set(authority) != required:
        raise ValueError("protected release tuple fields are not exact")
    expected = {
        "middleware_source_sha": values["SOURCE_SHA"],
        "middleware_digest": values["IMAGE_DIGEST"],
        "middleware_sbom_sha256": values["SBOM_SHA256"],
        "middleware_provenance_sha256": values["PROVENANCE_SHA256"],
        "middleware_openvex_sha256": values["OPENVEX_SHA256"],
        "middleware_run_id": run_id,
        "middleware_artifact": artifact,
    }
    for key, actual in expected.items():
        if authority[key] != actual:
            raise ValueError(f"protected release tuple {key} mismatch")
    for key in (
        "middleware_sbom_sha256",
        "middleware_provenance_sha256",
        "middleware_openvex_sha256",
    ):
        if not HASH_RE.fullmatch(authority[key]):
            raise ValueError("protected release tuple hashes are malformed")


def _validate_legacy(
    directory: Path,
    tuple_path: Path | None,
    run_id: str | None,
    artifact: str | None,
) -> dict[str, str]:
    values = release_environment(directory / "RELEASE.env")
    sbom_hash = hashlib.sha256((directory / "sbom.cdx.json").read_bytes()).hexdigest()
    if values["SBOM_SHA256"] != sbom_hash:
        raise ValueError("middleware SBOM hash differs from RELEASE.env")
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    build = provenance["buildDefinition"]
    if build["externalParameters"]["sourceSha"] != values["SOURCE_SHA"]:
        raise ValueError("middleware provenance source SHA differs")
    if provenance["subject"]["digest"] != values["IMAGE_DIGEST"]:
        raise ValueError("middleware provenance digest differs")
    if provenance["evidence"]["sbomSha256"] != sbom_hash:
        raise ValueError("middleware provenance SBOM binding differs")
    openvex_path = directory / "vex" / "openvex.json"
    openvex = json.loads(openvex_path.read_text(encoding="utf-8"))
    if openvex.get("metadata", {}).get("source_sha") != values["SOURCE_SHA"]:
        raise ValueError("middleware OpenVEX source SHA differs")
    if openvex.get("metadata", {}).get("image_digest") != values["IMAGE_DIGEST"]:
        raise ValueError("middleware OpenVEX subject digest differs")
    product_digest = values["IMAGE_DIGEST"].replace(":", "%3A")
    products = [
        product.get("@id", "")
        for statement in openvex.get("statements", [])
        for product in statement.get("products", [])
    ]
    if not products or any(product_digest not in product for product in products):
        raise ValueError("middleware OpenVEX products differ from release digest")
    builder = provenance["runDetails"]["builder"]["id"]
    if builder != CANONICAL_BUILDER:
        raise ValueError("middleware provenance builder is unauthorized")
    if not (directory / "signature-verification.txt").read_text(encoding="utf-8").strip():
        raise ValueError("middleware signature verification evidence is empty")
    if not (directory / "provenance-verification.txt").read_text(encoding="utf-8").strip():
        raise ValueError("middleware provenance verification evidence is empty")
    values["PROVENANCE_SHA256"] = hashlib.sha256(
        (directory / "provenance.json").read_bytes()
    ).hexdigest()
    values["OPENVEX_SHA256"] = hashlib.sha256(openvex_path.read_bytes()).hexdigest()
    values["MIGRATION_HEAD"] = ""
    values["BUILDER"] = builder
    if tuple_path is not None:
        _verify_tuple(tuple_path, values, run_id=run_id, artifact=artifact)
    return values


def _validate_signed(
    directory: Path,
    tuple_path: Path,
    run_id: str,
    artifact: str,
    artifact_digest: str,
    cosign: str,
    derived_provenance_output: Path | None,
    derived_openvex_output: Path | None,
) -> dict[str, str]:
    authority = json.loads(tuple_path.read_text(encoding="utf-8"))
    release = validate_signed_release(
        directory,
        expected_repository=CANONICAL_REPOSITORY,
        expected_image_repository=CANONICAL_IMAGE,
        expected_workflow_identity=CANONICAL_BUILDER,
        expected_source_sha=authority["middleware_source_sha"],
        expected_image_digest=authority["middleware_digest"],
        expected_run_id=run_id,
        artifact_name=artifact,
        artifact_digest=artifact_digest,
        cosign=cosign,
        verify_signature=True,
    )
    values = {
        "SOURCE_SHA": str(release["source_sha"]),
        "IMAGE_REFERENCE": str(release["image_reference"]),
        "IMAGE_DIGEST": str(release["image_digest"]),
        "SBOM_SHA256": str(release["sbom_sha256"]),
        "PROVENANCE_SHA256": str(release["provenance_sha256"]),
        "OPENVEX_SHA256": str(release["openvex_sha256"]),
        "MIGRATION_HEAD": str(release["migration_head"]),
        "BUILDER": str(release["builder"]),
        "RELEASE_MANIFEST_SHA256": str(release["release_manifest_sha256"]),
        "SIGSTORE_BUNDLE_SHA256": str(release["sigstore_bundle_sha256"]),
        "VULNERABILITY_REPORT_SHA256": str(release["vulnerability_report_sha256"]),
    }
    _verify_tuple(tuple_path, values, run_id=run_id, artifact=artifact)
    if derived_provenance_output is not None:
        derived_provenance_output.parent.mkdir(parents=True, exist_ok=True)
        derived_provenance_output.write_bytes(canonical_json(release["provenance"]))
    if derived_openvex_output is not None:
        derived_openvex_output.parent.mkdir(parents=True, exist_ok=True)
        derived_openvex_output.write_bytes(canonical_json(release["openvex"]))
    return values


def validate(
    directory: Path,
    tuple_path: Path | None = None,
    run_id: str | None = None,
    artifact: str | None = None,
    *,
    artifact_digest: str | None = None,
    cosign: str = "cosign",
    derived_provenance_output: Path | None = None,
    derived_openvex_output: Path | None = None,
) -> dict[str, str]:
    if (directory / "release-manifest.v1.json").is_file():
        if tuple_path is None or run_id is None or artifact is None or artifact_digest is None:
            raise ValueError("signed release verification requires exact tuple and artifact inputs")
        return _validate_signed(
            directory,
            tuple_path,
            run_id,
            artifact,
            artifact_digest,
            cosign,
            derived_provenance_output,
            derived_openvex_output,
        )
    return _validate_legacy(directory, tuple_path, run_id, artifact)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    parser.add_argument("--tuple", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--artifact-digest")
    parser.add_argument("--cosign", default="cosign")
    parser.add_argument("--derived-provenance-output", type=Path)
    parser.add_argument("--derived-openvex-output", type=Path)
    args = parser.parse_args()
    values = validate(
        args.directory,
        args.tuple,
        args.run_id,
        args.artifact,
        artifact_digest=args.artifact_digest,
        cosign=args.cosign,
        derived_provenance_output=args.derived_provenance_output,
        derived_openvex_output=args.derived_openvex_output,
    )
    with args.github_env.open("a", encoding="utf-8") as target:
        target.write(f'MIDDLEWARE_PROTECTED_SHA={values["SOURCE_SHA"]}\n')
        target.write(f'MIDDLEWARE_IMAGE_REFERENCE={values["IMAGE_REFERENCE"]}\n')
        target.write(f'MIDDLEWARE_IMAGE_DIGEST={values["IMAGE_DIGEST"]}\n')
        target.write(f'MIDDLEWARE_SBOM_SHA256={values["SBOM_SHA256"]}\n')
        target.write(f'MIDDLEWARE_PROVENANCE_SHA256={values["PROVENANCE_SHA256"]}\n')
        target.write(f'MIDDLEWARE_OPENVEX_SHA256={values["OPENVEX_SHA256"]}\n')
        target.write(f'MIDDLEWARE_MIGRATION_REVISION={values["MIGRATION_HEAD"]}\n')
        target.write(f'MIDDLEWARE_BUILDER={values["BUILDER"]}\n')
        if values.get("RELEASE_MANIFEST_SHA256"):
            target.write(
                f'MIDDLEWARE_RELEASE_MANIFEST_SHA256={values["RELEASE_MANIFEST_SHA256"]}\n'
            )
            target.write(
                f'MIDDLEWARE_SIGSTORE_BUNDLE_SHA256={values["SIGSTORE_BUNDLE_SHA256"]}\n'
            )
            target.write(
                'MIDDLEWARE_VULNERABILITY_REPORT_SHA256='
                f'{values["VULNERABILITY_REPORT_SHA256"]}\n'
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
