#!/usr/bin/env python3
"""Build a deterministic platform release bundle bound to one Middleware tuple."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any


FAIL_CLOSED_FLAGS = {
    "SEND_EVENTS": False,
    "ENABLE_EXTERNAL_DELIVERY": False,
    "ODOO_DELIVERY_ENABLED": False,
    "CALLBACK_DISPATCH": False,
    "ENABLE_VICIDIAL_WRITES": False,
    "LIVE_WRITE": False,
    "ODOO_WRITE": False,
    "N8N_DELIVERY_ENABLED": False,
    "PRODUCTION_DIALING": False,
    "LIVE_CALL_CONTROL": False,
    "GENERAL_AI_DIALING": False,
    "LIVE_EMAIL_DELIVERY": False,
    "LIVE_SMS_DELIVERY": False,
    "LIVE_PSTN_DIALING": False,
    "SOCIAL_PUBLISHING_ENABLED": False,
    "LIVE_ADVERTISING_ENABLED": False,
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
STAGING_ONLY_MIDDLEWARE_DIGEST = (
    "sha256:2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff"
)
SUPERSEDED_MIDDLEWARE_DIGESTS = {
    "sha256:336c9a31648a0481737fa4bcc3eafb02a22e4b4fc66ba7b8ec1759c087e05e02",
    "sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tracked_files(root: Path) -> list[Path]:
    output = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
    return [root / name.decode() for name in output.split(b"\0") if name]


def deterministic_archive(root: Path, files: list[Path], destination: Path) -> None:
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(files, key=lambda value: value.relative_to(root).as_posix()):
                    relative = path.relative_to(root)
                    info = archive.gettarinfo(
                        str(path), arcname=f"codestra/{relative.as_posix()}"
                    )
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    info.mtime = 0
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def load_tuple(path: Path) -> dict[str, Any]:
    authority = json.loads(path.read_text())
    if not isinstance(authority, dict) or set(authority) != TUPLE_FIELDS:
        raise ValueError("protected release tuple fields are not exact")
    if authority["schema_version"] != "codestra.production-release-tuple.v2":
        raise ValueError("protected release tuple schema is not v2")
    if authority["middleware_repository"] != "appolon1908-hue/Middleware-":
        raise ValueError("protected tuple Middleware repository is unauthorized")
    if authority["middleware_image_repository"] != (
        "ghcr.io/appolon1908-hue/codestra-middleware"
    ):
        raise ValueError("protected tuple Middleware image repository is unauthorized")
    if not SHA_RE.fullmatch(authority["middleware_source_sha"]):
        raise ValueError("protected tuple Middleware source SHA is invalid")
    if not SHA_RE.fullmatch(authority["middleware_source_tree"]):
        raise ValueError("protected tuple Middleware source tree is invalid")
    if not DIGEST_RE.fullmatch(authority["middleware_digest"]):
        raise ValueError("protected tuple Middleware digest is invalid")
    if authority["middleware_digest"] == STAGING_ONLY_MIDDLEWARE_DIGEST:
        raise ValueError("staging-only middleware digest is prohibited in production")
    if authority["middleware_digest"] in SUPERSEDED_MIDDLEWARE_DIGESTS:
        raise ValueError("superseded middleware digest is prohibited for new activation")
    for key in (
        "middleware_artifact_zip_sha256",
        "middleware_release_manifest_sha256",
        "middleware_sigstore_bundle_sha256",
        "middleware_sbom_sha256",
        "middleware_vulnerability_report_sha256",
    ):
        if not HASH_RE.fullmatch(authority[key]):
            raise ValueError(f"protected tuple {key} is invalid")
    if authority["middleware_external_effects_default"] != "disabled":
        raise ValueError("Middleware external effects must default to disabled")
    if authority["same_digest_promotion_required"] is not True:
        raise ValueError("same-digest staging and production promotion is required")
    if authority["production_deployment_authorized"] is not False:
        raise ValueError("repository release tuple must not self-authorize deployment")
    return authority


def build(
    root: Path,
    output: Path,
    commit: str,
    run_id: str,
    workflow_ref: str,
    middleware_image_signature_status: str,
    middleware_provenance_status: str,
    middleware_sbom_attestation_status: str,
    middleware_manifest_signature_status: str,
    migration_revision: str,
) -> None:
    if not SHA_RE.fullmatch(commit):
        raise ValueError("platform protected SHA must be exact")
    statuses = {
        "middleware_image_signature_verification": middleware_image_signature_status,
        "middleware_provenance_verification": middleware_provenance_status,
        "middleware_sbom_attestation_verification": middleware_sbom_attestation_status,
        "middleware_manifest_signature_verification": middleware_manifest_signature_status,
    }
    if any(value != "PASS" for value in statuses.values()):
        raise ValueError("all Middleware cryptographic verification statuses must be PASS")

    tuple_path = root / "config" / "production-release-tuple.json"
    authority = load_tuple(tuple_path)
    if migration_revision != authority["middleware_migration_head"]:
        raise ValueError("runtime migration revision differs from protected tuple")

    output.mkdir(parents=True, exist_ok=True)
    files = tracked_files(root)
    archive = output / f"codestra-production-platform-{commit}.tar.gz"
    deterministic_archive(root, files, archive)

    components = [
        {
            "type": "file",
            "name": path.relative_to(root).as_posix(),
            "hashes": [{"alg": "SHA-256", "content": sha256(path)}],
        }
        for path in sorted(files)
    ]
    write_json(
        output / "sbom.cdx.json",
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {
                "component": {
                    "type": "application",
                    "name": "codestra-production-platform",
                    "version": commit,
                }
            },
            "components": components,
        },
    )
    write_json(
        output / "provenance.json",
        {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": archive.name, "digest": {"sha256": sha256(archive)}}],
            "predicateType": "https://slsa.dev/provenance/v1",
            "predicate": {
                "buildDefinition": {
                    "buildType": "https://github.com/codestra/release-bundle/v2",
                    "externalParameters": {
                        "commit": commit,
                        "workflow_ref": workflow_ref,
                        "middleware_tuple_sha256": sha256(tuple_path),
                    },
                    "internalParameters": {},
                    "resolvedDependencies": [
                        {
                            "uri": (
                                "git+https://github.com/"
                                f"{authority['middleware_repository']}@"
                                f"{authority['middleware_source_sha']}"
                            ),
                            "digest": {
                                "gitTree": authority["middleware_source_tree"],
                                "sha256": authority["middleware_digest"].removeprefix(
                                    "sha256:"
                                ),
                            },
                        }
                    ],
                },
                "runDetails": {
                    "builder": {"id": workflow_ref},
                    "metadata": {"invocationId": run_id},
                },
            },
        },
    )

    release_tuple = {
        "orchestration_repository": "appolon1908-hue/codestra-production-platform",
        "orchestration_protected_sha": commit,
        "middleware_repository": authority["middleware_repository"],
        "middleware_protected_sha": authority["middleware_source_sha"],
        "middleware_source_tree": authority["middleware_source_tree"],
        "middleware_image": authority["middleware_image_repository"],
        "middleware_image_digest": authority["middleware_digest"],
        "middleware_migration_head": authority["middleware_migration_head"],
        "middleware_release_run_id": authority["middleware_run_id"],
        "middleware_release_run_attempt": authority["middleware_run_attempt"],
        "middleware_release_artifact_id": authority["middleware_artifact_id"],
        "middleware_release_artifact": authority["middleware_artifact"],
        "middleware_artifact_zip_sha256": authority[
            "middleware_artifact_zip_sha256"
        ],
        "middleware_release_manifest_sha256": authority[
            "middleware_release_manifest_sha256"
        ],
        "middleware_sigstore_bundle_sha256": authority[
            "middleware_sigstore_bundle_sha256"
        ],
        "middleware_sbom_sha256": authority["middleware_sbom_sha256"],
        "middleware_vulnerability_report_sha256": authority[
            "middleware_vulnerability_report_sha256"
        ],
        "middleware_workflow_identity": authority[
            "middleware_workflow_identity"
        ],
        "middleware_oidc_issuer": authority["middleware_oidc_issuer"],
        **statuses,
        "change_id": authority["change_id"],
        "release_version": authority["release_version"],
        "migration_revision": migration_revision,
        "jetstream_contract_sha256": sha256(
            root / "eventing/jetstream_contract.json"
        ),
        "keycloak_contract_sha256": sha256(
            root / "config/keycloak-production-contract.env.example"
        ),
        "release_tuple_authority_sha256": sha256(tuple_path),
        "production_deployment_authorized": False,
    }

    write_json(
        output / "deployment-manifest.json",
        {
            "schema_version": "codestra.deployment.v2",
            "commit": commit,
            "artifact": archive.name,
            "artifact_sha256": sha256(archive),
            "required_flags": FAIL_CLOSED_FLAGS,
            "deployment_mode": "digest-only-fail-closed",
            "release_tuple": release_tuple,
        },
    )
    write_json(
        output / "rollback-manifest.json",
        {
            "schema_version": "codestra.rollback.v2",
            "commit": commit,
            "preserve_events": True,
            "required_flags": FAIL_CLOSED_FLAGS,
            "rollback_requires_previous_verified_digest": True,
            "current_middleware_digest": authority["middleware_digest"],
            "production_deployment_authorized": False,
        },
    )
    evidence = sorted(output.glob("*.json")) + [archive]
    (output / "manifest.sha256").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in evidence)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--middleware-image-signature-status", required=True)
    parser.add_argument("--middleware-provenance-status", required=True)
    parser.add_argument("--middleware-sbom-attestation-status", required=True)
    parser.add_argument("--middleware-manifest-signature-status", required=True)
    parser.add_argument("--migration-revision", required=True)
    args = parser.parse_args()
    build(
        args.root.resolve(),
        args.output.resolve(),
        args.commit,
        args.run_id,
        args.workflow_ref,
        args.middleware_image_signature_status,
        args.middleware_provenance_status,
        args.middleware_sbom_attestation_status,
        args.middleware_manifest_signature_status,
        args.migration_revision,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
