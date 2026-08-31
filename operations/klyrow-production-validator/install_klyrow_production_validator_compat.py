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
ROLLBACK_LABELS = {
    "dispatcher",
    "root-helper",
    "actions",
    "core",
    "contract",
    "sudoers",
    "identity",
    "authorized_keys",
    "installation",
    "probe-core",
    "probe-authorization",
    "probe-no-effect",
    "probe-callback",
    "probe-smtp",
    "probe-manifest",
}


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


def validator_key_plan(
    target: Path, expected_fingerprint: str
) -> tuple[list[str], int, os.stat_result]:
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{20,60}", expected_fingerprint):
        raise InstallError("validator fingerprint rejected")
    validate_directory_chain(target.parent)
    if target.is_symlink() or not target.is_file():
        raise InstallError("authorized keys rejected")
    metadata = target.stat(follow_symlinks=False)
    if metadata.st_mode & 0o077:
        raise InstallError("authorized keys mode rejected")
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
    return retained, removed, metadata


def remove_validator_key(target: Path, expected_fingerprint: str) -> int:
    retained, removed, metadata = validator_key_plan(target, expected_fingerprint)
    if removed == 0:
        return 0
    temporary = target.with_name(".authorized_keys.kpv-rollback")
    if temporary.exists() or temporary.is_symlink():
        raise InstallError("rollback temporary target rejected")
    temporary.write_text("\n".join(retained) + ("\n" if retained else ""), encoding="utf-8")
    os.chmod(temporary, 0o600)
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


def preflight_backups(records: list[dict[str, object]], backup_dir: Path) -> None:
    labels = [record.get("label") for record in records]
    if (
        not all(isinstance(label, str) for label in labels)
        or len(labels) != len(set(labels))
        or not set(labels).issubset(ROLLBACK_LABELS)
    ):
        raise InstallError("rollback labels rejected")
    for record in records:
        present = record.get("present")
        required = {"target", "label", "present"}
        if present is True:
            required |= {"sha256", "uid", "gid", "mode"}
        if set(record) != required or not isinstance(present, bool):
            raise InstallError("rollback record schema rejected")
        target = Path(str(record["target"]))
        label = str(record["label"])
        if not target.is_absolute() or not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", label):
            raise InstallError("rollback record value rejected")
        validate_directory_chain(target.parent)
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise InstallError(f"unsafe rollback target: {target}")
        if present:
            digest = record.get("sha256")
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or not all(
                    isinstance(record.get(field), int)
                    and not isinstance(record.get(field), bool)
                    for field in ("uid", "gid", "mode")
                )
                or not 0 <= int(record["mode"]) <= 0o777
            ):
                raise InstallError("rollback backup metadata rejected")
            source = backup_dir / label
            try:
                metadata = source.lstat()
            except FileNotFoundError as exc:
                raise InstallError("rollback backup missing") from exc
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o077
                or sha256(source) != digest
            ):
                raise InstallError("rollback backup rejected")


def restore_backups(records: list[dict[str, object]], backup_dir: Path) -> None:
    preflight_backups(records, backup_dir)
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
