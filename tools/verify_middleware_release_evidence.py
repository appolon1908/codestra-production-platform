#!/usr/bin/env python3
"""Validate canonical middleware production evidence before tuple binding."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
STAGING_ONLY_DIGEST = (
    "sha256:2e15399387967c02d78cc56565157412f0cc2cb9ad6393695d17c39a88cdd2ff"
)


def release_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
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
    expected_reference = (
        "ghcr.io/codestra-srl/codestra-middleware@" + values["IMAGE_DIGEST"]
    )
    if values["IMAGE_REFERENCE"] != expected_reference:
        raise ValueError("middleware image reference and digest differ")
    return values


def validate(directory: Path) -> dict[str, str]:
    values = release_environment(directory / "RELEASE.env")
    sbom_hash = hashlib.sha256((directory / "sbom.cdx.json").read_bytes()).hexdigest()
    if values["SBOM_SHA256"] != sbom_hash:
        raise ValueError("middleware SBOM hash differs from RELEASE.env")
    provenance = json.loads((directory / "provenance.json").read_text())
    build = provenance["buildDefinition"]
    if build["externalParameters"]["sourceSha"] != values["SOURCE_SHA"]:
        raise ValueError("middleware provenance source SHA differs")
    if provenance["subject"]["digest"] != values["IMAGE_DIGEST"]:
        raise ValueError("middleware provenance digest differs")
    if provenance["evidence"]["sbomSha256"] != sbom_hash:
        raise ValueError("middleware provenance SBOM binding differs")
    openvex_path = directory / "vex" / "openvex.json"
    openvex = json.loads(openvex_path.read_text())
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
    if builder != (
        "https://github.com/Codestra-SRL/codestra-middleware/"
        ".github/workflows/exact-main-production-release.yml@refs/heads/main"
    ):
        raise ValueError("middleware provenance builder is unauthorized")
    if not (directory / "signature-verification.txt").read_text().strip():
        raise ValueError("middleware signature verification evidence is empty")
    if not (directory / "provenance-verification.txt").read_text().strip():
        raise ValueError("middleware provenance verification evidence is empty")
    values["PROVENANCE_SHA256"] = hashlib.sha256(
        (directory / "provenance.json").read_bytes()
    ).hexdigest()
    values["OPENVEX_SHA256"] = hashlib.sha256(openvex_path.read_bytes()).hexdigest()
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    args = parser.parse_args()
    values = validate(args.directory)
    with args.github_env.open("a") as target:
        target.write(f'MIDDLEWARE_PROTECTED_SHA={values["SOURCE_SHA"]}\n')
        target.write(f'MIDDLEWARE_IMAGE_DIGEST={values["IMAGE_DIGEST"]}\n')
        target.write(f'MIDDLEWARE_SBOM_SHA256={values["SBOM_SHA256"]}\n')
        target.write(f'MIDDLEWARE_PROVENANCE_SHA256={values["PROVENANCE_SHA256"]}\n')
        target.write(f'MIDDLEWARE_OPENVEX_SHA256={values["OPENVEX_SHA256"]}\n')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
