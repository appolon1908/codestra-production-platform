#!/usr/bin/env python3
"""Fail-closed, manifest-driven atomic secret-file replacement."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

FIELDS = (
    "service", "secret_id", "host_path", "container_path", "uid", "gid",
    "mode", "read_only", "restart_command", "read_check", "health_check",
    "new_auth_check", "old_auth_check",
)
FORBIDDEN_IDS = {(65534, 65534)}


class RotationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    service: str
    secret_id: str
    host_path: Path
    container_path: str
    uid: int
    gid: int
    mode: int
    read_only: bool
    restart_command: str
    read_check: str
    health_check: str
    new_auth_check: str
    old_auth_check: str


def load_entries(path: Path, service: str) -> list[Entry]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise RotationError("ownership manifest has invalid fields")
        rows = [row for row in reader if row["service"] == service]
    if not rows:
        raise RotationError("service is absent from ownership manifest")
    entries = []
    for row in rows:
        if not row["uid"].isdigit() or not row["gid"].isdigit():
            raise RotationError("numeric UID and GID are required")
        uid, gid = int(row["uid"]), int(row["gid"])
        if (uid, gid) in FORBIDDEN_IDS:
            raise RotationError("unexpected nobody:nogroup ownership")
        try:
            mode = int(row["mode"], 8)
        except ValueError as exc:
            raise RotationError("mode must be octal") from exc
        if mode <= 0 or mode & 0o077:
            raise RotationError("world/group-readable or writable mode rejected")
        if row["read_only"] != "true":
            raise RotationError("secret mount must be read-only")
        commands = (
            row["restart_command"], row["read_check"], row["health_check"],
            row["new_auth_check"], row["old_auth_check"],
        )
        if any(not command.strip() for command in commands):
            raise RotationError("all validation commands are required")
        entries.append(Entry(
            row["service"], row["secret_id"], Path(row["host_path"]),
            row["container_path"], uid, gid, mode, True, *commands,
        ))
    first = entries[0]
    for entry in entries[1:]:
        if (
            entry.restart_command, entry.health_check, entry.new_auth_check,
            entry.old_auth_check,
        ) != (
            first.restart_command, first.health_check, first.new_auth_check,
            first.old_auth_check,
        ):
            raise RotationError("service-level commands must agree on every row")
    return entries


def validate_destination(path: Path, approved_root: Path) -> os.stat_result:
    if path.is_symlink():
        raise RotationError("symlink destination rejected")
    try:
        current = path.stat()
    except FileNotFoundError as exc:
        raise RotationError("destination must already exist") from exc
    if not stat.S_ISREG(current.st_mode):
        raise RotationError("destination is not a regular file")
    root = approved_root.resolve(strict=True)
    parent = path.parent.resolve(strict=True)
    if parent != root and root not in parent.parents:
        raise RotationError("destination is outside approved root")
    return current


def atomic_write(path: Path, payload: bytes, uid: int, gid: int, mode: int,
                 fault: str | None = None) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.rotate-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if fault == "chown":
            raise PermissionError("injected chown failure")
        os.chown(temporary, uid, gid, follow_symlinks=False)
        os.chmod(temporary, mode, follow_symlinks=False)
        metadata = os.stat(temporary, follow_symlinks=False)
        if (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) != (
            uid, gid, mode,
        ):
            raise RotationError("temporary-file metadata verification failed")
        if metadata.st_size == 0:
            raise RotationError("empty secret rejected")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def run_check(command: str, expect_success: bool) -> bool:
    result = subprocess.run(
        command, shell=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False,
    )
    # Captured output is deliberately discarded: validators may emit credentials.
    return (result.returncode == 0) is expect_success


def metadata(path: Path) -> str:
    value = path.stat()
    return f"{value.st_uid}:{value.st_gid} {stat.S_IMODE(value.st_mode):03o}"


def capture_existing_metadata(path: Path) -> str:
    """Capture the required pre-replacement record without exposing file data."""
    result = subprocess.run(
        ["stat", "-c", "%u:%g %a", "--", str(path)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    value = result.stdout.strip()
    owner, mode = value.split()
    uid, gid = owner.split(":")
    if not uid.isdigit() or not gid.isdigit() or not mode.isdigit():
        raise RotationError("stat returned invalid numeric metadata")
    return f"{uid}:{gid} {int(mode, 8):03o}"


def write_evidence(path: Path, document: dict) -> None:
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def rotate(args: argparse.Namespace) -> None:
    entries = load_entries(args.manifest, args.service)
    records, backups = [], {}
    for entry in entries:
        before = validate_destination(entry.host_path, args.approved_root)
        if stat.S_IMODE(before.st_mode) != entry.mode:
            raise RotationError("existing mode differs from approved manifest")
        value_path = args.values_dir / entry.secret_id
        if value_path.is_symlink() or not value_path.is_file():
            raise RotationError("new secret source must be a regular non-symlink file")
        payload = value_path.read_bytes()
        if not payload:
            raise RotationError("empty secret rejected")
        backups[entry.secret_id] = entry.host_path.read_bytes()
        records.append({
            "service": entry.service, "secret_id": entry.secret_id,
            "host_path": str(entry.host_path),
            "container_path": entry.container_path,
            "before": capture_existing_metadata(entry.host_path),
            "approved": f"{entry.uid}:{entry.gid} {entry.mode:03o}",
            "read_only": True,
        })

    replaced: list[Entry] = []
    try:
        for entry in entries:
            atomic_write(
                entry.host_path, (args.values_dir / entry.secret_id).read_bytes(),
                entry.uid, entry.gid, entry.mode, args.fault,
            )
            replaced.append(entry)
            if metadata(entry.host_path) != f"{entry.uid}:{entry.gid} {entry.mode:03o}":
                raise RotationError("post-replacement metadata mismatch")
        first = entries[0]
        checks = (
            ("restart", first.restart_command, True),
            *[(f"read:{entry.secret_id}", entry.read_check, True) for entry in entries],
            ("health", first.health_check, True),
            ("new_credential_accepted", first.new_auth_check, True),
            ("old_credential_rejected", first.old_auth_check, False),
        )
        results = {}
        for name, command, expected in checks:
            passed = run_check(command, expected)
            results[name] = "PASS" if passed else "FAIL"
            if not passed:
                raise RotationError(f"{name} validation failed")
        for record, entry in zip(records, entries):
            record["after"] = metadata(entry.host_path)
        write_evidence(args.evidence, {
            "gate": "SECRET_ROTATION_SERVICE_OWNERSHIP_GATE",
            "result": "SERVICE_ROTATION_PASS",
            "service": args.service, "files": records, "checks": results,
            "contains_secret_values": False,
        })
    except BaseException as original:
        rollback_ok = True
        for entry in reversed(replaced):
            try:
                before = records[entries.index(entry)]["before"].split()
                owner = before[0].split(":")
                atomic_write(
                    entry.host_path, backups[entry.secret_id],
                    int(owner[0]), int(owner[1]), int(before[1], 8),
                )
            except BaseException:
                rollback_ok = False
        if replaced:
            rollback_ok = run_check(entries[0].restart_command, True) and rollback_ok
        write_evidence(args.evidence, {
            "gate": "SECRET_ROTATION_SERVICE_OWNERSHIP_GATE",
            "result": "FAIL", "service": args.service,
            "rollback": "PASS" if rollback_ok else "FAIL",
            "files": records, "contains_secret_values": False,
        })
        raise RotationError(
            f"rotation failed; rollback={'PASS' if rollback_ok else 'FAIL'}"
        ) from original
    finally:
        for key in list(backups):
            backups[key] = b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--values-dir", type=Path, required=True)
    parser.add_argument("--approved-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--fault", choices=("chown",))
    args = parser.parse_args()
    try:
        rotate(args)
    except RotationError as exc:
        print(f"ROTATION_RESULT=FAIL reason={exc}", file=sys.stderr)
        return 1
    print("ROTATION_RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
