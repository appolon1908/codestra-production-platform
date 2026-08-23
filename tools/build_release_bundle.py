#!/usr/bin/env python3
"""Build a deterministic, source-only release bundle and bound evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import tarfile
from pathlib import Path


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
}
STAGING_ONLY_MIDDLEWARE_DIGEST = (
    "sha256:2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff"
)
SUPERSEDED_MIDDLEWARE_DIGESTS = {
    "sha256:336c9a31648a0481737fa4bcc3eafb02a22e4b4fc66ba7b8ec1759c087e05e02",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tracked_files(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z"]
    )
    return [root / name.decode() for name in output.split(b"\0") if name]


def deterministic_archive(root: Path, files: list[Path], destination: Path) -> None:
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(files, key=lambda value: value.relative_to(root).as_posix()):
                    relative = path.relative_to(root)
                    info = archive.gettarinfo(str(path), arcname=f"codestra/{relative.as_posix()}")
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    info.mtime = 0
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def build(
    root: Path,
    output: Path,
    commit: str,
    run_id: str,
    workflow_ref: str,
    middleware_sha: str,
    middleware_image_digest: str,
    middleware_signature_status: str,
    middleware_provenance_status: str,
    middleware_sbom_sha256: str,
    middleware_provenance_sha256: str,
    middleware_openvex_sha256: str,
    migration_revision: str,
) -> None:
    if not SHA_RE.fullmatch(commit) or not SHA_RE.fullmatch(middleware_sha):
        raise ValueError("platform and middleware protected SHAs must be exact")
    if not DIGEST_RE.fullmatch(middleware_image_digest):
        raise ValueError("middleware image digest must be immutable sha256")
    if middleware_image_digest == STAGING_ONLY_MIDDLEWARE_DIGEST:
        raise ValueError("staging-only middleware digest is prohibited in production")
    if middleware_image_digest in SUPERSEDED_MIDDLEWARE_DIGESTS:
        raise ValueError("superseded middleware digest is prohibited for new activation")
    evidence_hashes = {
        "middleware_sbom_sha256": middleware_sbom_sha256,
        "middleware_provenance_sha256": middleware_provenance_sha256,
        "middleware_openvex_sha256": middleware_openvex_sha256,
    }
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in evidence_hashes.values()):
        raise ValueError("middleware evidence hashes must be exact sha256 values")
    if middleware_signature_status != "PASS":
        raise ValueError("middleware production signature verification is required")
    if middleware_provenance_status != "PASS":
        raise ValueError("middleware production provenance verification is required")
    if not migration_revision or migration_revision == "REQUIRED":
        raise ValueError("exact migration revision is required")
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
            "metadata": {"component": {"type": "application", "name": "codestra-production-platform", "version": commit}},
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
                    "buildType": "https://github.com/codestra/release-bundle/v1",
                    "externalParameters": {"commit": commit, "workflow_ref": workflow_ref},
                    "internalParameters": {},
                    "resolvedDependencies": [],
                },
                "runDetails": {
                    "builder": {"id": workflow_ref},
                    "metadata": {"invocationId": run_id},
                },
            },
        },
    )
    write_json(
        output / "deployment-manifest.json",
        {
            "schema_version": "codestra.deployment.v1",
            "commit": commit,
            "artifact": archive.name,
            "artifact_sha256": sha256(archive),
            "required_flags": FAIL_CLOSED_FLAGS,
            "deployment_mode": "digest-only-fail-closed",
            "release_tuple": {
                "orchestration_repository": (
                    "appolon1908-hue/codestra-production-platform"
                ),
                "orchestration_protected_sha": commit,
                "middleware_repository": "Codestra-SRL/codestra-middleware",
                "middleware_protected_sha": middleware_sha,
                "middleware_image": "ghcr.io/codestra-srl/codestra-middleware",
                "middleware_image_digest": middleware_image_digest,
                "middleware_signature_verification": middleware_signature_status,
                "middleware_provenance_verification": middleware_provenance_status,
                **evidence_hashes,
                "migration_revision": migration_revision,
                "jetstream_contract_sha256": sha256(
                    root / "eventing/jetstream_contract.json"
                ),
                "keycloak_contract_sha256": sha256(
                    root / "config/keycloak-production-contract.env.example"
                ),
                "release_tuple_authority_sha256": sha256(
                    root / "docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md"
                ),
            },
        },
    )
    write_json(
        output / "rollback-manifest.json",
        {
            "schema_version": "codestra.rollback.v1",
            "commit": commit,
            "preserve_events": True,
            "required_flags": FAIL_CLOSED_FLAGS,
            "rollback_requires_previous_verified_digest": True,
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
    parser.add_argument("--middleware-sha", required=True)
    parser.add_argument("--middleware-image-digest", required=True)
    parser.add_argument("--middleware-signature-status", required=True)
    parser.add_argument("--middleware-provenance-status", required=True)
    parser.add_argument("--middleware-sbom-sha256", required=True)
    parser.add_argument("--middleware-provenance-sha256", required=True)
    parser.add_argument("--middleware-openvex-sha256", required=True)
    parser.add_argument("--migration-revision", required=True)
    args = parser.parse_args()
    build(
        args.root.resolve(),
        args.output.resolve(),
        args.commit,
        args.run_id,
        args.workflow_ref,
        args.middleware_sha,
        args.middleware_image_digest,
        args.middleware_signature_status,
        args.middleware_provenance_status,
        args.middleware_sbom_sha256,
        args.middleware_provenance_sha256,
        args.middleware_openvex_sha256,
        args.migration_revision,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
