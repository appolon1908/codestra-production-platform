#!/usr/bin/env python3
"""Validate signed SLSA provenance and copied Codestra evidence bindings."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any


STATEMENT_TYPE = "https://in-toto.io/Statement/v0.1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
AUTHORIZED_BUILDER = (
    "https://github.com/Codestra-SRL/codestra-middleware/"
    ".github/workflows/exact-main-production-release.yml@refs/heads/main"
)
EXPECTED_BUILD_TYPE = (
    "https://codestra.example/buildtypes/exact-main-middleware-production/v1"
)
SOURCE_REPOSITORY = "https://github.com/Codestra-SRL/codestra-middleware"
CANONICAL_IMAGE = "ghcr.io/codestra-srl/codestra-middleware"
STAGING_ONLY_DIGEST = (
    "sha256:2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SLSA_FIELDS = ("buildDefinition", "runDetails")
EVIDENCE_FILES = {
    "sbomSha256": "sbom",
    "trivySha256": "trivy",
    "grypeSha256": "grype",
}


def release_environment(path: Path) -> dict[str, str]:
    """Parse the exact legacy Codestra-SRL RELEASE.env evidence contract.

    This compatibility parser intentionally remains local to the SLSA verifier.
    The Appolon Middleware authority verifier has a different signed-manifest
    contract and must not replace or reinterpret historical Codestra-SRL evidence.
    """

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


def _documents(path: Path) -> list[dict[str, Any]]:
    text = path.read_text().strip()
    if not text:
        raise ValueError("provenance verification output is empty")
    try:
        parsed = json.loads(text)
        values = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        try:
            values = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ValueError("provenance verification output is malformed JSON") from exc
    if not values or any(not isinstance(value, dict) for value in values):
        raise ValueError("provenance verification documents must be JSON objects")
    return values


def _statement(document: dict[str, Any]) -> dict[str, Any]:
    payload = document.get("payload")
    if not isinstance(payload, str) or not payload:
        raise ValueError("verified provenance document has no payload")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("verified provenance payload is invalid base64") from exc
    try:
        statement = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("verified provenance payload is invalid JSON") from exc
    if not isinstance(statement, dict):
        raise ValueError("verified provenance statement must be a JSON object")
    return statement


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_subject(statement: dict[str, Any], image_name: str, digest: str) -> None:
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise ValueError("signed provenance must contain exactly one subject")
    subject = subjects[0]
    expected_hex = digest.removeprefix("sha256:")
    if not isinstance(subject, dict) or subject.get("name") != image_name:
        raise ValueError("signed provenance subject name differs from RELEASE.env")
    digests = subject.get("digest")
    if not isinstance(digests, dict) or set(digests) != {"sha256"}:
        raise ValueError("signed provenance subject digest algorithm is unsupported")
    actual = digests["sha256"]
    if not isinstance(actual, str) or not HEX_DIGEST_RE.fullmatch(actual):
        raise ValueError("signed provenance subject SHA256 is malformed")
    if actual != expected_hex:
        raise ValueError("signed provenance subject digest differs from RELEASE.env")


def validate(
    verification: Path,
    provenance_path: Path,
    release_env_path: Path,
    sbom_path: Path,
    trivy_path: Path,
    grype_path: Path,
) -> None:
    release = release_environment(release_env_path)
    try:
        provenance = json.loads(provenance_path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError("copied middleware provenance is malformed JSON") from exc
    if not isinstance(provenance, dict) or set(provenance) != {
        *SLSA_FIELDS,
        "subject",
        "evidence",
    }:
        raise ValueError("copied middleware provenance fields are not exact")

    expected_predicate = {field: provenance[field] for field in SLSA_FIELDS}
    expected_build = {
        "buildType": EXPECTED_BUILD_TYPE,
        "externalParameters": {
            "sourceSha": release["SOURCE_SHA"],
            "platform": "linux/amd64",
        },
        "resolvedDependencies": [
            {
                "uri": f"git+{SOURCE_REPOSITORY}@{release['SOURCE_SHA']}",
                "digest": {"gitCommit": release["SOURCE_SHA"]},
            }
        ],
    }
    if expected_predicate["buildDefinition"] != expected_build:
        raise ValueError("middleware SLSA build definition is unauthorized")
    if expected_predicate["runDetails"] != {"builder": {"id": AUTHORIZED_BUILDER}}:
        raise ValueError("middleware provenance builder is unauthorized")
    if provenance["subject"] != {"digest": release["IMAGE_DIGEST"]}:
        raise ValueError("copied middleware provenance subject differs from RELEASE.env")

    evidence = provenance["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != set(EVIDENCE_FILES):
        raise ValueError("copied middleware provenance evidence fields are not exact")
    evidence_paths = {"sbom": sbom_path, "trivy": trivy_path, "grype": grype_path}
    actual_hashes = {
        field: _sha256(evidence_paths[file_name])
        for field, file_name in EVIDENCE_FILES.items()
    }
    if evidence != actual_hashes:
        raise ValueError("copied middleware provenance evidence hash differs")
    if release["SBOM_SHA256"] != actual_hashes["sbomSha256"]:
        raise ValueError("middleware SBOM hash differs from RELEASE.env")

    image_name = release["IMAGE_REFERENCE"].rsplit("@", 1)[0]
    for document in _documents(verification):
        statement = _statement(document)
        if statement.get("_type") != STATEMENT_TYPE:
            raise ValueError("verified provenance statement type is invalid")
        if statement.get("predicateType") != PREDICATE_TYPE:
            raise ValueError("verified provenance predicate type is invalid")
        _validate_subject(statement, image_name, release["IMAGE_DIGEST"])
        if statement.get("predicate") != expected_predicate:
            raise ValueError("signed SLSA predicate differs from copied provenance")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--release-env", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--trivy", type=Path, required=True)
    parser.add_argument("--grype", type=Path, required=True)
    args = parser.parse_args()
    validate(
        args.verification,
        args.provenance,
        args.release_env,
        args.sbom,
        args.trivy,
        args.grype,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
