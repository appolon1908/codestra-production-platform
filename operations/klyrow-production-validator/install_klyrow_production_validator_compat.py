"""Import bridge for the hyphenated installer filename.

The released command remains ``install-klyrow-production-validator.py``. This
module exposes the small, fixed rollback and authorized-key primitives shared
by the revoker and uninstaller.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
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


def read_private_text(path: Path, *, maximum_bytes: int = 1024 * 1024) -> tuple[str, os.stat_result]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o077:
            raise InstallError("private file rejected")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                raise InstallError("private file too large")
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable):
            raise InstallError("private file changed during read")
        current = path.lstat()
        if current.st_dev != after.st_dev or current.st_ino != after.st_ino:
            raise InstallError("private file path changed during read")
    finally:
        os.close(descriptor)
    try:
        return b"".join(chunks).decode("utf-8"), after
    except UnicodeDecodeError as exc:
        raise InstallError("private file encoding rejected") from exc


def atomic_replace_text(
    target: Path,
    content: str,
    expected_target: os.stat_result,
    *,
    label: str,
) -> None:
    if not re.fullmatch(r"[a-z0-9-]{3,32}", label):
        raise InstallError("temporary label rejected")
    validate_directory_chain(target.parent)
    temporary: Path | None = None
    descriptor: int | None = None
    for _attempt in range(32):
        candidate = target.with_name(f".{target.name}.kpv-{label}.{secrets.token_hex(12)}")
        try:
            descriptor = os.open(
                candidate,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                0o600,
            )
            temporary = candidate
            break
        except FileExistsError:
            continue
    if descriptor is None or temporary is None:
        raise InstallError("secure temporary file unavailable")
    try:
        encoded = content.encode("utf-8")
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise InstallError("temporary file write failed")
            written += count
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, expected_target.st_uid, expected_target.st_gid)
        os.fsync(descriptor)
        created = os.fstat(descriptor)
        temporary_metadata = temporary.lstat()
        if (
            not stat.S_ISREG(temporary_metadata.st_mode)
            or temporary_metadata.st_dev != created.st_dev
            or temporary_metadata.st_ino != created.st_ino
        ):
            raise InstallError("secure temporary file replaced")
        current = target.lstat()
        stable_target = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(
            getattr(current, field) != getattr(expected_target, field)
            for field in stable_target
        ):
            raise InstallError("authorized keys changed before replace")
        os.replace(temporary, target)
        installed = target.lstat()
        if (
            not stat.S_ISREG(installed.st_mode)
            or installed.st_dev != created.st_dev
            or installed.st_ino != created.st_ino
        ):
            raise InstallError("authorized keys replacement rejected")
        temporary = None
    finally:
        os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    text, metadata = read_private_text(target)
    retained: list[str] = []
    removed = 0
    unexpected_forced = 0
    for line in text.splitlines():
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
    atomic_replace_text(
        target,
        "\n".join(retained) + ("\n" if retained else ""),
        metadata,
        label="rollback",
    )
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
