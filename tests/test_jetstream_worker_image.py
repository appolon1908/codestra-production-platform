from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from tools.verify_jetstream_worker_image import verify


DIGEST = "sha256:" + "a" * 64
IMAGE = "ghcr.io/appolon1908-hue/codestra-middleware"


def write_manifest(path):
    path.write_text(
        json.dumps(
            {
                "release_tuple": {
                    "middleware_image": IMAGE,
                    "middleware_image_digest": DIGEST,
                    "production_deployment_authorized": False,
                }
            }
        )
    )


def signed_inputs(tmp_path, manifest, monkeypatch):
    checksums = tmp_path / "manifest.sha256"
    checksums.write_text(
        f"{hashlib.sha256(manifest.read_bytes()).hexdigest()}  {manifest.name}\n"
    )
    signature = tmp_path / "manifest.sha256.sig"
    signature.write_text("synthetic-signature")
    signers = tmp_path / "allowed_signers"
    signers.write_text("codestra-release synthetic-public-key")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("tools.verify_jetstream_worker_image.subprocess.run", run)
    return checksums, signature, signers, calls


def test_worker_image_must_equal_signed_release_tuple(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "deployment-manifest.json"
    environment = tmp_path / "worker.env"
    write_manifest(manifest)
    expected = f"{IMAGE}@{DIGEST}"
    environment.write_text(f"MIDDLEWARE_IMAGE={expected}\n")
    checksums, signature, signers, calls = signed_inputs(
        tmp_path, manifest, monkeypatch
    )
    assert verify(manifest, environment, checksums, signature, signers) == expected
    assert calls and calls[0][1]["input"] == checksums.read_bytes()


@pytest.mark.parametrize(
    "selected",
    [
        IMAGE + ":latest",
        IMAGE + "@sha256:" + "b" * 64,
        "ghcr.io/codestra-srl/codestra-middleware@sha256:" + "a" * 64,
    ],
)
def test_worker_image_rejects_mutable_different_or_former_authority(
    tmp_path, monkeypatch, selected
) -> None:
    manifest = tmp_path / "deployment-manifest.json"
    environment = tmp_path / "worker.env"
    write_manifest(manifest)
    environment.write_text(f"MIDDLEWARE_IMAGE={selected}\n")
    checksums, signature, signers, _calls = signed_inputs(
        tmp_path, manifest, monkeypatch
    )
    with pytest.raises(ValueError, match="differs from signed release tuple"):
        verify(manifest, environment, checksums, signature, signers)


def test_worker_image_rejects_manifest_outside_signed_checksums(
    tmp_path, monkeypatch
) -> None:
    manifest = tmp_path / "deployment-manifest.json"
    environment = tmp_path / "worker.env"
    write_manifest(manifest)
    expected = f"{IMAGE}@{DIGEST}"
    environment.write_text(f"MIDDLEWARE_IMAGE={expected}\n")
    checksums, signature, signers, _calls = signed_inputs(
        tmp_path, manifest, monkeypatch
    )
    manifest.write_text(manifest.read_text() + "\n")
    with pytest.raises(ValueError, match="differs from signed manifest"):
        verify(manifest, environment, checksums, signature, signers)


def test_worker_image_rejects_self_authorizing_manifest(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "deployment-manifest.json"
    environment = tmp_path / "worker.env"
    write_manifest(manifest)
    value = json.loads(manifest.read_text())
    value["release_tuple"]["production_deployment_authorized"] = True
    manifest.write_text(json.dumps(value))
    expected = f"{IMAGE}@{DIGEST}"
    environment.write_text(f"MIDDLEWARE_IMAGE={expected}\n")
    checksums, signature, signers, _calls = signed_inputs(
        tmp_path, manifest, monkeypatch
    )
    with pytest.raises(ValueError, match="must not self-authorize"):
        verify(manifest, environment, checksums, signature, signers)
