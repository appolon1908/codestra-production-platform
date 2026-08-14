#!/usr/bin/env python3
"""Fail closed unless the DLQ worker image equals the signed release tuple."""

from __future__ import annotations

import argparse
import json
import re
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


def verify(manifest_path: Path, environment_path: Path) -> str:
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
    args = parser.parse_args()
    print(f"jetstream_worker_image={verify(args.manifest, args.environment)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
