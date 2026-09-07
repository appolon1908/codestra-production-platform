#!/usr/bin/env python3
"""Bind live Cosign-verified attestations to the authenticated v1 release manifest.

Run after verify_middleware_release_evidence.py has authenticated the original
manifest, bundle, evidence hashes and protected tuple. Cosign must authenticate
both registry verification files before this content validation.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

try:
    from tools.verify_attestation_predicate import (
        _canonical_predicate,
        _loads,
        documents as _documents,
        statement as _statement,
    )
    from tools.verify_slsa_provenance_attestation import (
        AUTHORIZED_BUILDER,
        EXPECTED_BUILD_TYPE,
        SOURCE_REPOSITORY,
        _validate_subject,
    )
except ModuleNotFoundError:
    from verify_attestation_predicate import (
        _canonical_predicate,
        _loads,
        documents as _documents,
        statement as _statement,
    )
    from verify_slsa_provenance_attestation import (
        AUTHORIZED_BUILDER,
        EXPECTED_BUILD_TYPE,
        SOURCE_REPOSITORY,
        _validate_subject,
    )


def validate(
    manifest_path: Path,
    sbom_path: Path,
    provenance: Path,
    sbom: Path,
    expected_source: str,
    expected_digest: str,
) -> None:
    manifest = _loads(manifest_path.read_text(encoding="utf-8"))
    image_name = "ghcr.io/appolon1908-hue/codestra-middleware"
    if (
        manifest["source"]["git_sha"] != expected_source
        or manifest["image"]["digest"] != expected_digest
        or manifest["image"]["repository"] != image_name
        or manifest["image"]["reference"] != image_name + "@" + expected_digest
        or manifest["build"]["workflow_identity"] != AUTHORIZED_BUILDER
        or manifest["image"]["platforms"] != ["linux/amd64"]
    ):
        raise ValueError("signed manifest differs from protected release authority")
    if manifest["artifacts"]["sbom"] != {
        "path": "middleware.spdx.json",
        "sha256": "sha256:" + hashlib.sha256(sbom_path.read_bytes()).hexdigest(),
    }:
        raise ValueError("SPDX SBOM differs from signed manifest")
    predicate = {
        "buildDefinition": {
            "buildType": EXPECTED_BUILD_TYPE,
            "externalParameters": {
                "sourceSha": expected_source,
                "platform": "linux/amd64",
            },
            "resolvedDependencies": [
                {
                    "uri": f"git+{SOURCE_REPOSITORY}@{expected_source}",
                    "digest": {"gitCommit": expected_source},
                }
            ],
        },
        "runDetails": {"builder": {"id": AUTHORIZED_BUILDER}},
    }
    for path, kind, expected in (
        (provenance, "https://slsa.dev/provenance/v1", predicate),
        (sbom, "https://spdx.dev/Document", _loads(sbom_path.read_text(encoding="utf-8"))),
    ):
        expected_json = _canonical_predicate(expected)
        for document in _documents(path):
            statement = _statement(document)
            if statement.get("_type") != "https://in-toto.io/Statement/v0.1":
                raise ValueError("invalid attestation statement type")
            if statement.get("predicateType") != kind:
                raise ValueError("invalid attestation predicate type")
            _validate_subject(statement, image_name, expected_digest)
            if _canonical_predicate(statement["predicate"]) != expected_json:
                raise ValueError("attestation differs from signed release evidence")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--provenance-verification", type=Path, required=True)
    parser.add_argument("--sbom-verification", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--expected-digest", required=True)
    args = parser.parse_args()
    validate(
        args.manifest,
        args.sbom,
        args.provenance_verification,
        args.sbom_verification,
        args.expected_source,
        args.expected_digest,
    )


if __name__ == "__main__":
    main()
