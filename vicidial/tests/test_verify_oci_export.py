from __future__ import annotations

import hashlib
import io
import json
import runpy
import sys
import tarfile

import pytest


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _direct_oci_archive(path, source_sha: str, architecture: str = "amd64") -> str:
    config = _json_bytes({
        "architecture": architecture,
        "os": "linux",
        "config": {"Labels": {"org.opencontainers.image.revision": source_sha}},
    })
    config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest = _json_bytes({
        "schemaVersion": 2,
        "config": {"digest": config_digest},
        "layers": [],
    })
    manifest_digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
    index = _json_bytes({
        "schemaVersion": 2,
        "manifests": [{"digest": manifest_digest}],
    })
    with tarfile.open(path, "w") as archive:
        _write_member(archive, "index.json", index)
        _write_member(archive, f"blobs/sha256/{config_digest.split(':')[1]}", config)
        _write_member(archive, f"blobs/sha256/{manifest_digest.split(':')[1]}", manifest)
    return config_digest


def _run_verifier(monkeypatch, tmp_path, architecture: str = "amd64"):
    source_sha = "a" * 40
    archive = tmp_path / "image.oci.tar"
    image_id = _direct_oci_archive(archive, source_sha, architecture)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps([{"Id": image_id}]))
    output = tmp_path / "verification.json"
    monkeypatch.setattr(sys, "argv", [
        "verify_oci_export.py",
        "--archive", str(archive),
        "--metadata", str(metadata),
        "--source-sha", source_sha,
        "--output", str(output),
    ])
    return output


def test_verifier_accepts_direct_single_platform_manifest(monkeypatch, tmp_path):
    output = _run_verifier(monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path("vicidial/scripts/verify_oci_export.py", run_name="__main__")
    assert json.loads(output.read_text())["status"] == "PASS"


def test_verifier_rejects_direct_wrong_platform(monkeypatch, tmp_path):
    _run_verifier(monkeypatch, tmp_path, architecture="arm64")
    with pytest.raises(ValueError, match="linux/amd64"):
        runpy.run_path("vicidial/scripts/verify_oci_export.py", run_name="__main__")
