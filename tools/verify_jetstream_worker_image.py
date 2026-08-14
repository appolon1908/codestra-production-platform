#!/usr/bin/env python3
"""Fail closed unless the DLQ worker image equals the signed release tuple."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


IMAGE_RE = re.compile(
    r"^ghcr[.]io/codestra-srl/codestra-middleware@sha256:[0-9a-f]{64}$"
)


def environment_value(path: Path, name: str) -> str:
    values = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    if name not in values:
        raise ValueError(f"{name} is missing from worker environment")
    return values[name]


def verify_signed_checksum(
    checksum_path: Path,
    signature_path: Path,
    allowed_signers_path: Path,
    identity: str,
) -> None:
    subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(allowed_signers_path),
            "-I",
            identity,
            "-n",
            "codestra-release",
            "-s",
            str(signature_path),
        ],
        input=checksum_path.read_bytes(),
        check=True,
        stdout=subprocess.DEVNULL,
    )


def verify_checksum(manifest_path: Path, checksum_path: Path) -> None:
    expected = None
    for line in checksum_path.read_text().splitlines():
        digest, separator, name = line.partition("  ")
        if separator and name == manifest_path.name:
            expected = digest
            break
    actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if expected is None or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("deployment manifest checksum is missing")
    if actual != expected:
        raise ValueError("deployment manifest checksum differs from signed manifest")


def verify(
    manifest_path: Path,
    environment_path: Path,
    checksum_path: Path,
    signature_path: Path,
    allowed_signers_path: Path,
    identity: str = "codestra-release",
) -> str:
    verify_signed_checksum(
        checksum_path, signature_path, allowed_signers_path, identity
    )
    verify_checksum(manifest_path, checksum_path)
    manifest = json.loads(manifest_path.read_text())
    release = manifest["release_tuple"]
    expected = f"{release['middleware_image']}@{release['middleware_image_digest']}"
    selected = environment_value(environment_path, "MIDDLEWARE_IMAGE")
    if not IMAGE_RE.fullmatch(expected) or selected != expected:
        raise ValueError("worker image differs from signed release tuple")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--checksums", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--identity", default="codestra-release")
    args = parser.parse_args()
    print(
        "jetstream_worker_image="
        f"{verify(args.manifest, args.environment, args.checksums, args.signature, args.allowed_signers, args.identity)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
