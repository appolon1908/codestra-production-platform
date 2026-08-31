"""Import bridge for the hyphenated installer filename.

The released command remains ``install-klyrow-production-validator.py``. This
module exposes only the two rollback primitives needed by the uninstaller.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


class InstallError(RuntimeError):
    pass


FORCED = 'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch"'


def key_fingerprint(key_type: str, key_blob: str) -> str | None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", delete=True) as handle:
        handle.write(f"{key_type} {key_blob}\n")
        handle.flush()
        result = subprocess.run(
            ["/usr/bin/ssh-keygen", "-lf", handle.name],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    return result.stdout.split()[1] if result.returncode == 0 else None


def remove_validator_key(target: Path, expected_fingerprint: str) -> int:
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{20,60}", expected_fingerprint):
        raise InstallError("validator fingerprint rejected")
    validate_directory_chain(target.parent)
    if target.is_symlink() or not target.is_file():
        raise InstallError("authorized keys rejected")
    retained: list[str] = []
    removed = 0
    unexpected_forced = 0
    for line in target.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        matched = False
        if FORCED in line:
            observed_fingerprint = None
            for index, value in enumerate(fields[:-1]):
                if value == "ssh-ed25519":
                    observed_fingerprint = key_fingerprint(value, fields[index + 1])
                    break
            matched = observed_fingerprint == expected_fingerprint
            if not matched:
                unexpected_forced += 1
        if matched:
            removed += 1
        else:
            retained.append(line)
    if removed > 1 or unexpected_forced:
        raise InstallError("validator key drift rejected")
    temporary = target.with_name(".authorized_keys.kpv-rollback")
    if temporary.exists() or temporary.is_symlink():
        raise InstallError("rollback temporary target rejected")
    temporary.write_text("\n".join(retained) + ("\n" if retained else ""), encoding="utf-8")
    os.chmod(temporary, 0o600)
    metadata = target.stat(follow_symlinks=False)
    os.chown(temporary, metadata.st_uid, metadata.st_gid)
    os.replace(temporary, target)
    return removed


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
