#!/usr/bin/env python3
"""Validate an isolated Odoo database/filestore restore without reading content."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


class ValidationError(RuntimeError):
    pass


def parse_metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        if raw and not raw.startswith("#"):
            key, value = raw.split("=", 1)
            values[key] = value
    required = {"BACKUP_ID", "DATABASE", "FILESTORE_RELATIVE", "ODOO_UID", "ODOO_GID"}
    if missing := required - values.keys():
        raise ValidationError(f"backup metadata missing {sorted(missing)}")
    return values


def validate(
    metadata_path: Path,
    restored_data_dir: Path,
    attachment_map: Path,
    expected_backup_id: str,
    restored_database: str | None = None,
) -> dict[str, int | str | list[str]]:
    metadata = parse_metadata(metadata_path)
    if metadata["BACKUP_ID"] != expected_backup_id:
        raise ValidationError("database/filestore backup ID mismatch")
    relative = Path(metadata["FILESTORE_RELATIVE"])
    if restored_database:
        relative = relative.parent / restored_database
    filestore = restored_data_dir / relative
    if not filestore.is_dir():
        raise ValidationError("restored filestore directory is missing")
    uid, gid = int(metadata["ODOO_UID"]), int(metadata["ODOO_GID"])
    directory_paths = [restored_data_dir]
    cursor = restored_data_dir
    for part in relative.parts:
        cursor = cursor / part
        directory_paths.append(cursor)
    # Inspect directories before recursively touching their children.  pathlib's
    # rglob may yield an entry below a non-traversable shard and then leak a raw
    # PermissionError from is_dir() when the validator runs as the Odoo user.
    # os.walk lets us stat the shard itself and prune it before descending.
    for root, directory_names, _ in os.walk(filestore, followlinks=False):
        root_path = Path(root)
        traversable_names = []
        for directory_name in directory_names:
            directory_path = root_path / directory_name
            directory_paths.append(directory_path)
            try:
                mode = directory_path.stat().st_mode
            except OSError as exc:
                raise ValidationError("filestore directory traversal failures: 1") from exc
            if mode & 0o100:
                traversable_names.append(directory_name)
        directory_names[:] = traversable_names
    directory_ownership_failures = []
    directory_traversal_failures = []
    for path in directory_paths:
        stat = path.stat()
        name = str(path.relative_to(restored_data_dir)) or "."
        if (stat.st_uid, stat.st_gid) != (uid, gid):
            directory_ownership_failures.append(name)
        if not stat.st_mode & 0o100:
            directory_traversal_failures.append(name)
    if directory_ownership_failures:
        raise ValidationError(f"filestore directory ownership failures: {len(directory_ownership_failures)}")
    if directory_traversal_failures:
        raise ValidationError(f"filestore directory traversal failures: {len(directory_traversal_failures)}")
    references: dict[str, str] = {}
    for line in attachment_map.read_text().splitlines():
        if "|" not in line:
            raise ValidationError("attachment map contains a malformed row")
        store_fname, checksum = line.split("|", 1)
        if not store_fname.strip() or not checksum.strip():
            raise ValidationError("attachment map contains a blank filename or checksum")
        if store_fname in references and references[store_fname] != checksum:
            raise ValidationError("attachment map contains conflicting checksums for one filename")
        references[store_fname] = checksum
    files = {str(path.relative_to(filestore)): path for path in filestore.rglob("*") if path.is_file()}
    missing = sorted(set(references) - set(files))
    orphans = sorted(set(files) - set(references))
    mismatches = []
    ownership_failures = []
    for name, path in files.items():
        stat = path.stat()
        if (stat.st_uid, stat.st_gid) != (uid, gid):
            ownership_failures.append(name)
        expected = references.get(name)
        if expected and hashlib.sha1(path.read_bytes()).hexdigest() != expected:
            mismatches.append(name)
    if missing:
        raise ValidationError(f"missing filestore objects: {len(missing)}")
    if mismatches:
        raise ValidationError(f"filestore checksum mismatches: {len(mismatches)}")
    if ownership_failures:
        raise ValidationError(f"filestore ownership failures: {len(ownership_failures)}")
    return {
        "backup_id": metadata["BACKUP_ID"],
        "referenced_objects": len(references),
        "filestore_objects": len(files),
        "missing_objects": 0,
        "checksum_mismatches": 0,
        "ownership_failures": 0,
        "directory_ownership_failures": 0,
        "directory_traversal_failures": 0,
        "orphan_objects": len(orphans),
        "orphan_files": orphans,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--attachment-map", type=Path, required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--restored-database")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(
        args.metadata,
        args.data_dir,
        args.attachment_map,
        args.backup_id,
        args.restored_database,
    )
    rendered = json.dumps(result, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
