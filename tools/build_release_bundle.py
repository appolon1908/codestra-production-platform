#!/usr/bin/env python3
"""Build a deterministic, source-only release bundle and bound evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path


FAIL_CLOSED_FLAGS = {
    "SEND_EVENTS": False,
    "ENABLE_EXTERNAL_DELIVERY": False,
    "LIVE_WRITE": False,
    "ODOO_WRITE": False,
    "N8N_DELIVERY_ENABLED": False,
    "PRODUCTION_DIALING": False,
    "LIVE_CALL_CONTROL": False,
    "GENERAL_AI_DIALING": False,
}


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


def build(root: Path, output: Path, commit: str, run_id: str, workflow_ref: str) -> None:
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
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"name": archive.name, "digest": {"sha256": sha256(archive)}}],
            "buildDefinition": {
                "buildType": "https://github.com/codestra/release-bundle/v1",
                "externalParameters": {"commit": commit, "workflow_ref": workflow_ref},
            },
            "runDetails": {"builder": {"id": workflow_ref}, "metadata": {"invocationId": run_id}},
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
    args = parser.parse_args()
    build(args.root.resolve(), args.output.resolve(), args.commit, args.run_id, args.workflow_ref)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
