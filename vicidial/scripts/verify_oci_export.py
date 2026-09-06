#!/usr/bin/env python3.11
"""Prove an OCI export is the same platform image tested in Docker."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path


def member_bytes(archive: tarfile.TarFile, name: str) -> bytes:
    try:
        member = archive.extractfile(name)
    except KeyError as exc:
        raise ValueError(f"OCI member missing: {name}") from exc
    if member is None:
        raise ValueError(f"OCI member missing: {name}")
    return member.read()


def member_json(archive: tarfile.TarFile, name: str) -> dict:
    return json.loads(member_bytes(archive, name))


def descriptor_bytes(archive: tarfile.TarFile, descriptor: dict) -> bytes:
    digest = descriptor.get("digest")
    size = descriptor.get("size")
    if not isinstance(digest, str) or not isinstance(size, int) or size < 0:
        raise ValueError("OCI descriptor digest or size missing")
    algorithm, value = digest.split(":", 1)
    if algorithm != "sha256" or len(value) != 64:
        raise ValueError("OCI digest is not SHA-256")
    raw = member_bytes(archive, f"blobs/sha256/{value}")
    if len(raw) != size:
        raise ValueError("OCI descriptor size mismatch")
    if hashlib.sha256(raw).hexdigest() != value:
        raise ValueError("OCI blob digest mismatch")
    return raw


def blob_json(archive: tarfile.TarFile, descriptor: dict) -> dict:
    return json.loads(descriptor_bytes(archive, descriptor))


def layer_diff_id(raw: bytes, media_type: str) -> str:
    if media_type.endswith("+gzip"):
        try:
            payload = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except (OSError, EOFError) as exc:
            raise ValueError("OCI layer gzip compression is invalid") from exc
    elif media_type in {
        "application/vnd.oci.image.layer.v1.tar",
        "application/vnd.docker.image.rootfs.diff.tar",
    }:
        payload = raw
    else:
        raise ValueError(f"unsupported OCI layer media type: {media_type}")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))[0]
    expected_config = metadata["Id"]
    with tarfile.open(args.archive, "r") as archive:
        try:
            layout = json.loads(member_bytes(archive, "oci-layout"))
        except json.JSONDecodeError as exc:
            raise ValueError("OCI layout metadata is invalid JSON") from exc
        if not isinstance(layout, dict) or layout.get("imageLayoutVersion") != "1.0.0":
            raise ValueError("OCI image layout version is not 1.0.0")
        index = member_json(archive, "index.json")
        if not isinstance(index, dict) or index.get("schemaVersion") != 2:
            raise ValueError("OCI index schema version is not 2")
        roots = index.get("manifests", [])
        if len(roots) != 1:
            raise ValueError("OCI archive does not contain exactly one root manifest")
        root_descriptor = roots[0]
        outer = blob_json(archive, root_descriptor)
        if not isinstance(outer, dict) or outer.get("schemaVersion") != 2:
            raise ValueError("OCI root manifest schema version is not 2")
        if "manifests" in outer:
            candidates = [
                item for item in outer["manifests"]
                if item.get("platform") == {"architecture": "amd64", "os": "linux"}
            ]
            if len(candidates) != 1:
                raise ValueError("OCI archive does not contain one linux/amd64 image")
            manifest_descriptor = candidates[0]
            manifest = blob_json(archive, manifest_descriptor)
        elif "config" in outer:
            manifest_descriptor = root_descriptor
            manifest = outer
        else:
            raise ValueError("OCI root is neither an image manifest nor an image index")
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
            raise ValueError("OCI image manifest schema version is not 2")
        if manifest["config"]["digest"] != expected_config:
            raise ValueError("OCI config digest differs from tested Docker image ID")
        config = blob_json(archive, manifest["config"])
        if (config.get("architecture"), config.get("os")) != ("amd64", "linux"):
            raise ValueError("OCI archive does not contain one linux/amd64 image")
        labels = config.get("config", {}).get("Labels", {})
        if labels.get("org.opencontainers.image.revision") != args.source_sha:
            raise ValueError("OCI source revision differs from exact head")
        layers = manifest.get("layers")
        diff_ids = config.get("rootfs", {}).get("diff_ids")
        if not isinstance(layers, list) or not isinstance(diff_ids, list):
            raise ValueError("OCI layer or rootfs identity is missing")
        if len(layers) != len(diff_ids):
            raise ValueError("OCI layer and rootfs diff-ID counts differ")
        computed_diff_ids = [
            layer_diff_id(descriptor_bytes(archive, layer), layer.get("mediaType", ""))
            for layer in layers
        ]
        if computed_diff_ids != diff_ids:
            raise ValueError("OCI layer content differs from rootfs diff IDs")
        tested_diff_ids = metadata.get("RootFS", {}).get("Layers")
        if tested_diff_ids != diff_ids:
            raise ValueError("OCI rootfs differs from tested Docker image")
        layout_sha256 = hashlib.sha256(member_bytes(archive, "oci-layout")).hexdigest()
        index_sha256 = hashlib.sha256(member_bytes(archive, "index.json")).hexdigest()

    document = {
        "schema": "codestra-oci-export-verification/v1",
        "source_sha": args.source_sha,
        "docker_image_id": expected_config,
        "oci_manifest_digest": manifest_descriptor["digest"],
        "oci_config_digest": manifest["config"]["digest"],
        "oci_layer_digests": [item["digest"] for item in layers],
        "rootfs_diff_ids": diff_ids,
        "oci_layout_sha256": layout_sha256,
        "index_sha256": index_sha256,
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "status": "PASS",
    }
    args.output.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    print("OCI_EXPORT_VERIFICATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
