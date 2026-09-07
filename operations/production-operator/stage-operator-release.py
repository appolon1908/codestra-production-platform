#!/usr/bin/env python3
"""Verify and safely stage a reviewed operator release archive.

This command does not install the operator.  Production usage is deliberately
fixed beneath /opt/codestra-operator-releases.  CODESTRA_STAGE_ROOT is accepted
only with --test-root so tests can use a disposable filesystem.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class StageError(Exception):
    pass


def secure_path(path: Path, *, kind: str, mode: int, uid: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise StageError(f"{kind} is unavailable") from exc
    if kind == "archive" and not stat.S_ISREG(info.st_mode):
        raise StageError("archive must be a regular file")
    if kind == "archive" and info.st_nlink != 1:
        raise StageError("archive must not have additional hard links")
    if kind != "archive" and not stat.S_ISDIR(info.st_mode):
        raise StageError(f"{kind} must be a directory")
    if info.st_uid != uid or info.st_gid != uid:
        raise StageError(f"unsafe {kind} ownership")
    if stat.S_IMODE(info.st_mode) != mode:
        raise StageError(f"unsafe {kind} permissions")


def validate_members(bundle: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = bundle.getmembers()
    if not members:
        raise StageError("archive is empty")
    destinations: dict[PurePosixPath, str] = {}
    for member in members:
        raw = member.name
        path = PurePosixPath(raw)
        if not raw or raw.startswith("/") or "\x00" in raw or ".." in path.parts:
            raise StageError(f"unsafe archive member: {raw!r}")
        normalized = PurePosixPath(*[part for part in path.parts if part not in ("", ".")])
        if not normalized.parts:
            raise StageError("archive member has empty destination")
        if member.issym() or member.islnk():
            raise StageError(f"archive links are forbidden: {raw!r}")
        if not (member.isfile() or member.isdir()):
            raise StageError(f"archive special file is forbidden: {raw!r}")
        member_kind = "directory" if member.isdir() else "file"
        if normalized in destinations:
            raise StageError(f"duplicate archive destination: {normalized}")
        for parent in normalized.parents:
            if parent == PurePosixPath("."):
                continue
            if destinations.get(parent) == "file":
                raise StageError(f"conflicting archive destination: {normalized}")
        if member_kind == "file" and any(p != normalized and p.is_relative_to(normalized) for p in destinations):
            raise StageError(f"conflicting archive destination: {normalized}")
        destinations[normalized] = member_kind
    return members


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def stage(archive: Path, approved: str, release: str, root: Path, uid: int) -> Path:
    source = root / "source"
    snapshots = root / "snapshots"
    staged = root / "staged"
    for directory, label in ((root, "release root"), (source, "source directory")):
        secure_path(directory, kind=label, mode=0o700, uid=uid)
    if not archive.is_absolute():
        raise StageError("archive path must be absolute")
    if archive.parent != source:
        raise StageError("archive must be directly inside the controlled source directory")
    secure_path(archive, kind="archive", mode=0o600, uid=uid)
    destination = staged / release
    if destination.exists() or destination.is_symlink():
        raise StageError("staging destination already exists")
    for directory, label in ((snapshots, "snapshot directory"), (staged, "staged directory")):
        if directory.exists() or directory.is_symlink():
            secure_path(directory, kind=label, mode=0o700, uid=uid)
    snapshots.mkdir(mode=0o700, exist_ok=True)
    staged.mkdir(mode=0o700, exist_ok=True)
    secure_path(snapshots, kind="snapshot directory", mode=0o700, uid=uid)
    secure_path(staged, kind="staged directory", mode=0o700, uid=uid)
    descriptor, snapshot_name = tempfile.mkstemp(prefix=f".{release}.", suffix=".tar", dir=snapshots)
    snapshot = Path(snapshot_name)
    work = Path(tempfile.mkdtemp(prefix=f".{release}.", dir=staged))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output, archive.open("rb") as source_stream:
            shutil.copyfileobj(source_stream, output)
            output.flush()
            os.fsync(output.fileno())
        if digest(snapshot) != approved:
            raise StageError("archive checksum does not match the approved digest")
        with tarfile.open(snapshot, mode="r:*") as bundle:
            members = validate_members(bundle)
            for member in members:
                target = work.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    target.mkdir(mode=0o755, parents=True, exist_ok=False)
                    target.chmod(0o755)
                else:
                    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                    source_file = bundle.extractfile(member)
                    if source_file is None:
                        raise StageError("archive member could not be read")
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                    with source_file, os.fdopen(os.open(target, flags, 0o600), "wb") as output:
                        shutil.copyfileobj(source_file, output)
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
        for item in work.rglob("*"):
            info = item.lstat()
            if info.st_uid != uid or info.st_gid != uid or not (item.is_file() or item.is_dir()) or item.is_symlink():
                raise StageError("staged tree ownership or file type is unsafe")
            allowed = 0o755 if item.is_dir() or info.st_mode & 0o111 else 0o644
            if stat.S_IMODE(info.st_mode) != allowed:
                raise StageError("staged tree permissions are unsafe")
        work.rename(destination)
        return destination
    except (OSError, tarfile.TarError) as exc:
        raise StageError("archive staging failed safely") from exc
    finally:
        if work.exists():
            shutil.rmtree(work)
        snapshot.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("approved_sha256")
    parser.add_argument("release_id")
    parser.add_argument("--test-root", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.archive or not HEX64.fullmatch(args.approved_sha256) or not RELEASE.fullmatch(args.release_id):
        print("STAGE_RESULT=FAIL\nFAILURE_REASON=invalid required input", file=sys.stderr)
        return 2
    root = Path("/opt/codestra-operator-releases")
    expected_uid = 0
    if args.test_root:
        configured = os.environ.get("CODESTRA_STAGE_ROOT", "")
        if not configured or not Path(configured).is_absolute():
            print("STAGE_RESULT=FAIL\nFAILURE_REASON=test root is invalid", file=sys.stderr)
            return 2
        root, expected_uid = Path(configured), os.geteuid()
    elif os.geteuid() != 0 or "CODESTRA_STAGE_ROOT" in os.environ:
        print("STAGE_RESULT=FAIL\nFAILURE_REASON=root-controlled production staging is required", file=sys.stderr)
        return 2
    try:
        destination = stage(Path(args.archive), args.approved_sha256, args.release_id, root, expected_uid)
    except StageError as exc:
        print(f"STAGE_RESULT=FAIL\nFAILURE_REASON={exc}", file=sys.stderr)
        return 2
    print(f"STAGE_RESULT=PASS\nSTAGED_RELEASE={destination}\nPRODUCTION_INSTALLED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
