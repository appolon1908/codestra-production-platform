from __future__ import annotations

import json

import pytest

from tools.verify_jetstream_worker_image import verify


DIGEST = "sha256:" + "a" * 64


def write_manifest(path):
    path.write_text(
        json.dumps(
            {
                "release_tuple": {
                    "middleware_image": "ghcr.io/codestra-srl/codestra-middleware",
                    "middleware_image_digest": DIGEST,
                }
            }
        )
    )


def test_worker_image_must_equal_signed_release_tuple(tmp_path) -> None:
    manifest = tmp_path / "deployment-manifest.json"
    environment = tmp_path / "worker.env"
    write_manifest(manifest)
    expected = f"ghcr.io/codestra-srl/codestra-middleware@{DIGEST}"
    environment.write_text(f"MIDDLEWARE_IMAGE={expected}\n")
    assert verify(manifest, environment) == expected


@pytest.mark.parametrize(
    "selected",
    [
        "ghcr.io/codestra-srl/codestra-middleware:latest",
        "ghcr.io/codestra-srl/codestra-middleware@sha256:" + "b" * 64,
    ],
)
def test_worker_image_rejects_mutable_or_different_artifact(tmp_path, selected) -> None:
    manifest = tmp_path / "deployment-manifest.json"
    environment = tmp_path / "worker.env"
    write_manifest(manifest)
    environment.write_text(f"MIDDLEWARE_IMAGE={selected}\n")
    with pytest.raises(ValueError, match="differs from signed release tuple"):
        verify(manifest, environment)
