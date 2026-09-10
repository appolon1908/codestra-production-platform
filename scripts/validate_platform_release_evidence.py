#!/usr/bin/env python3
"""Check a release instance and the exact, environment-bound evidence bytes.

This is an offline consistency gate, not a signature verifier or authorization
for a deployment. Invoke after independently obtaining the accepted evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 4 * 1024 * 1024


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_json(data: bytes) -> dict[str, Any]:
    value = json.loads(data, object_pairs_hook=_pairs,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON value")))
    if not isinstance(value, dict):
        raise ValueError("evidence must contain a JSON object")
    return value


def pinned_bytes(root: Path, reference: dict[str, Any]) -> bytes:
    name = reference.get("path")
    digest = reference.get("sha256")
    if (not isinstance(name, str) or not name or "\\" in name
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or digest == "0" * 64):
        raise ValueError("invalid pinned-file identity")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
        raise ValueError("noncanonical evidence path")
    root = root.resolve(strict=True)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("symlink evidence is forbidden")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_BYTES:
        raise ValueError("evidence must be a bounded nonempty regular file")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("pinned-file digest mismatch")
    return data


def validate_release_evidence(manifest: dict[str, Any], *, root: Path = ROOT) -> None:
    """Reject relabelled staging evidence and incomplete/changed artifact pins."""
    schema = json.loads((ROOT / "release/platform-release-manifest.v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
    for reference in (manifest["contracts"], manifest["runtime"],
                      manifest["edge"]["caddy"], manifest["edge"]["kong"]):
        pinned_bytes(root, reference)
    index = {(ref["path"], ref["sha256"], ref["environment"])
             for ref in manifest["evidence"]}
    if len(index) != len(manifest["evidence"]):
        raise ValueError("duplicate evidence index entry")
    for ref in manifest["evidence"]:
        pinned_bytes(root, ref)
    # A manifest label cannot change the originating environment or candidate
    # named inside the artifact. Every gate and class has its own evidence.
    service_digests = {service["service_id"]: service["image"]["digest"]
                       for service in manifest["services"]}
    used_paths: set[str] = set()
    used_digests: set[str] = set()
    used_index: set[tuple[str, str, str]] = set()
    for environment in ("staging", "production"):
        gate = manifest["promotion"][environment]
        for kind, reference in gate["evidence"].items():
            identity = (reference["path"], reference["sha256"], environment)
            if identity not in index:
                raise ValueError("promotion artifact missing from evidence index")
            if reference["path"] in used_paths or reference["sha256"] in used_digests:
                raise ValueError("promotion evidence must be distinct across environments and classes")
            evidence = read_json(pinned_bytes(root, reference))
            expected = {
                "schema_version": "platform-promotion-evidence.v1",
                "environment": environment,
                "evidence_class": kind,
                "release_id": manifest["release_id"],
                "authority_git_sha": manifest["authority"]["git_sha"],
                "service_digests": service_digests,
                "result": "PASS",
            }
            if any(evidence.get(key) != value for key, value in expected.items()):
                raise ValueError("promotion artifact environment, class, result or release subject mismatch")
            used_paths.add(reference["path"])
            used_digests.add(reference["sha256"])
            used_index.add(identity)
    if used_index != index:
        raise ValueError("unbound artifact in promotion evidence index")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        validate_release_evidence(read_json(args.manifest.read_bytes()), root=args.evidence_root)
    except (OSError, ValueError, TypeError, KeyError, ValidationError) as exc:
        # Do not echo arbitrary artifact contents or authentication material.
        print(f"PLATFORM_RELEASE_EVIDENCE=FAIL error={type(exc).__name__}")
        return 2
    print("PLATFORM_RELEASE_EVIDENCE=PASS")
    print("DEPLOYMENT_AUTHORIZED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
