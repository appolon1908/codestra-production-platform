#!/usr/bin/env python3
"""Provision the release signer from an independently verified public key."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path


FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def normalized_key(source: Path) -> bytes:
    value = source.read_text().strip()
    fields = value.split()
    if len(fields) < 2 or not fields[0].startswith("ssh-"):
        raise ValueError("release signing public key is invalid")
    return f"{fields[0]} {fields[1]}".encode()


def provision(source: Path, expected_sha256: str, destination: Path) -> str:
    key = normalized_key(source)
    if not FINGERPRINT_RE.fullmatch(expected_sha256):
        raise ValueError("exact public-key SHA-256 fingerprint is required")
    actual = hashlib.sha256(key).hexdigest()
    if actual != expected_sha256:
        raise ValueError("release signing public key fingerprint mismatch")
    content = b"codestra-release " + key + b"\n"
    if destination.exists():
        if destination.read_bytes() != content:
            raise ValueError("a different release trust anchor is already installed")
        os.chmod(destination, 0o644)
        return actual
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".allowed_signers.", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("/etc/codestra/release/allowed_signers"),
    )
    args = parser.parse_args()
    fingerprint = provision(
        args.public_key, args.expected_sha256, args.destination
    )
    print(f"release_trust_anchor_sha256={fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
