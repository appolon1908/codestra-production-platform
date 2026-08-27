from __future__ import annotations

import hashlib
import gzip
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


def _descriptor(payload: bytes, media_type: str | None = None) -> dict:
    value = {"digest": "sha256:" + hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    if media_type:
        value["mediaType"] = media_type
    return value


def _direct_oci_archive(path, source_sha: str, architecture: str = "amd64") -> tuple[str, str]:
    layer_payload = b"deterministic layer contents\n"
    layer = gzip.compress(layer_payload, mtime=0)
    layer_descriptor = _descriptor(layer, "application/vnd.oci.image.layer.v1.tar+gzip")
    diff_id = "sha256:" + hashlib.sha256(layer_payload).hexdigest()
    config = _json_bytes({
        "architecture": architecture,
        "os": "linux",
        "config": {"Labels": {"org.opencontainers.image.revision": source_sha}},
        "rootfs": {"type": "layers", "diff_ids": [diff_id]},
    })
    config_descriptor = _descriptor(config)
    config_digest = config_descriptor["digest"]
    manifest = _json_bytes({
        "schemaVersion": 2,
        "config": config_descriptor,
        "layers": [layer_descriptor],
    })
    manifest_descriptor = _descriptor(manifest)
    manifest_digest = manifest_descriptor["digest"]
    index = _json_bytes({
        "schemaVersion": 2,
        "manifests": [manifest_descriptor],
    })
    with tarfile.open(path, "w") as archive:
        _write_member(archive, "oci-layout", _json_bytes({"imageLayoutVersion": "1.0.0"}))
        _write_member(archive, "index.json", index)
        _write_member(archive, f"blobs/sha256/{config_digest.split(':')[1]}", config)
        _write_member(archive, f"blobs/sha256/{manifest_digest.split(':')[1]}", manifest)
        _write_member(archive, f"blobs/sha256/{layer_descriptor['digest'].split(':')[1]}", layer)
    return config_digest, diff_id


def _run_verifier(monkeypatch, tmp_path, architecture: str = "amd64"):
    source_sha = "a" * 40
    archive = tmp_path / "image.oci.tar"
    image_id, diff_id = _direct_oci_archive(archive, source_sha, architecture)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps([{"Id": image_id, "RootFS": {"Layers": [diff_id]}}]))
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


@pytest.mark.parametrize("mutation,match", [
    ("missing", "member missing: oci-layout"),
    ("version", "layout version is not 1.0.0"),
    ("malformed", "layout metadata is invalid JSON"),
])
def test_verifier_rejects_invalid_oci_layout(monkeypatch, tmp_path, mutation, match):
    source_sha = "a" * 40
    archive_path = tmp_path / "image.oci.tar"
    image_id, diff_id = _direct_oci_archive(archive_path, source_sha)
    with tarfile.open(archive_path, "r") as source:
        members = {item.name: source.extractfile(item).read() for item in source if item.isfile()}
    if mutation == "missing":
        del members["oci-layout"]
    elif mutation == "version":
        members["oci-layout"] = _json_bytes({"imageLayoutVersion": "0.9.0"})
    else:
        members["oci-layout"] = b"not json"
    with tarfile.open(archive_path, "w") as target:
        for name, payload in members.items():
            _write_member(target, name, payload)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps([{"Id": image_id, "RootFS": {"Layers": [diff_id]}}]))
    output = tmp_path / "verification.json"
    monkeypatch.setattr(sys, "argv", ["verify_oci_export.py", "--archive", str(archive_path),
        "--metadata", str(metadata), "--source-sha", source_sha, "--output", str(output)])
    with pytest.raises(ValueError, match=match):
        runpy.run_path("vicidial/scripts/verify_oci_export.py", run_name="__main__")


@pytest.mark.parametrize("mutation,match", [
    ("blob", "blob digest mismatch"),
    ("size", "descriptor size mismatch"),
    ("missing", "member missing"),
    ("extra", "counts differ"),
    ("reordered", "diff-ID"),
    ("truncated", "descriptor size mismatch"),
    ("compression", "compression is invalid"),
])
def test_verifier_rejects_layer_identity_failures(monkeypatch, tmp_path, mutation, match):
    source_sha = "a" * 40
    archive_path = tmp_path / "image.oci.tar"
    image_id, diff_id = _direct_oci_archive(archive_path, source_sha)
    with tarfile.open(archive_path, "r") as source:
        members = {item.name: source.extractfile(item).read() for item in source if item.isfile()}
    index = json.loads(members["index.json"])
    manifest_name = "blobs/sha256/" + index["manifests"][0]["digest"].split(":")[1]
    manifest = json.loads(members[manifest_name])
    layer_name = "blobs/sha256/" + manifest["layers"][0]["digest"].split(":")[1]
    if mutation == "blob":
        members[layer_name] = members[layer_name][:-1] + b"x"
    elif mutation == "size":
        manifest["layers"][0]["size"] += 1
    elif mutation == "missing":
        del members[layer_name]
    elif mutation == "extra":
        manifest["layers"].append(manifest["layers"][0])
    elif mutation == "reordered":
        manifest["layers"].append(manifest["layers"][0])
        metadata_diff_ids = [diff_id, "sha256:" + "b" * 64]
    elif mutation == "truncated":
        members[layer_name] = members[layer_name][:-2]
    elif mutation == "compression":
        replacement = b"not gzip"
        descriptor = _descriptor(replacement, "application/vnd.oci.image.layer.v1.tar+gzip")
        manifest["layers"][0] = descriptor
        del members[layer_name]
        layer_name = "blobs/sha256/" + descriptor["digest"].split(":")[1]
        members[layer_name] = replacement
    if mutation in {"size", "extra", "reordered", "compression"}:
        members[manifest_name] = _json_bytes(manifest)
        updated = _descriptor(members[manifest_name])
        del members[manifest_name]
        index["manifests"][0] = updated
        manifest_name = "blobs/sha256/" + updated["digest"].split(":")[1]
        members[manifest_name] = _json_bytes(manifest)
        members["index.json"] = _json_bytes(index)
    metadata_diff_ids = locals().get("metadata_diff_ids", [diff_id])
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps([{"Id": image_id, "RootFS": {"Layers": metadata_diff_ids}}]))
    with tarfile.open(archive_path, "w") as target:
        for name, payload in members.items():
            _write_member(target, name, payload)
    output = tmp_path / "verification.json"
    monkeypatch.setattr(sys, "argv", ["verify_oci_export.py", "--archive", str(archive_path),
        "--metadata", str(metadata), "--source-sha", source_sha, "--output", str(output)])
    with pytest.raises(ValueError, match=match):
        runpy.run_path("vicidial/scripts/verify_oci_export.py", run_name="__main__")
