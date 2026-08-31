"""Import bridge for the hyphenated installer filename.

The released command remains ``install-klyrow-production-validator.py``. This
module exposes only the two rollback primitives needed by the uninstaller.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path


class InstallError(RuntimeError):
    pass


def validate_directory_chain(path: Path) -> None:
    if not path.is_absolute():
        raise InstallError("directory path must be absolute")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise InstallError(f"unsafe directory ancestor: {current}")


def mapped(root: Path | None, absolute: str) -> Path:
    path = Path(absolute)
    if not path.is_absolute():
        raise InstallError("installation target must be absolute")
    return path if root is None else root / path.relative_to("/")


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def restore_backups(records: list[dict[str, object]], backup_dir: Path) -> None:
    for record in reversed(records):
        target = Path(str(record["target"]))
        validate_directory_chain(target.parent)
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise InstallError(f"unsafe rollback target: {target}")
        target.unlink(missing_ok=True)
        if record.get("present"):
            source = backup_dir / str(record["label"])
            if sha256(source) != record.get("sha256"):
                raise InstallError("rollback backup checksum mismatch")
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
            os.chown(target, int(record["uid"]), int(record["gid"]))
            os.chmod(target, int(record["mode"]))
