#!/usr/bin/env python3.11
"""Generate a reviewable local in-toto provenance statement for an image."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--oci-verification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = "docker" if shutil.which("docker") else "podman"
    inspect = json.loads(subprocess.check_output(
        [engine, "image", "inspect", args.image], text=True))[0]
    verification = json.loads(args.oci_verification.read_text(encoding="utf-8"))
    digest = verification.get("oci_manifest_digest", "")
    if (verification.get("status") != "PASS" or
            verification.get("source_sha") != args.source_sha or
            not digest.startswith("sha256:") or len(digest) != 71):
        raise ValueError("verified OCI manifest identity is required")
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": args.image, "digest": {"sha256": digest.removeprefix("sha256:")}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": f"https://codestra.example/buildtypes/{engine}/v1",
                "externalParameters": {"platform": "linux/amd64"},
                "resolvedDependencies": [{
                    "uri": "git+https://github.com/appolon1908-hue/codestra-production-platform",
                    "digest": {"gitCommit": args.source_sha},
                }],
            },
            "runDetails": {
                "builder": {"id": f"local:{engine}"},
                "metadata": {"invocationId": inspect["Id"]},
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(statement, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
