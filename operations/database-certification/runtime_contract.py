#!/usr/bin/env python3
"""Fail-closed runtime discovery and evidence helpers for Server A.

This module intentionally uses Docker Compose labels rather than generated
container names. All helpers are read-only unless a caller explicitly runs a
Docker command that creates an isolated restore resource.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DIGEST_IMAGE_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
REMOTE_RE = re.compile(r"^(?P<host>(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9][A-Za-z0-9_.-]*):(?P<path>/[^\n\r]*)$")


class ContractError(RuntimeError):
    """Raised when runtime identity or protected-input validation fails."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    stdout: bytes
    stderr: bytes
    returncode: int


def run_command(
    args: Sequence[str],
    *,
    input_bytes: bytes | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = 120,
    check: bool = True,
) -> CommandResult:
    """Run a command without a shell and return byte-accurate output."""
    try:
        completed = subprocess.run(
            list(args),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=None if env is None else dict(env),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        command = " ".join(str(value) for value in args[:3])
        raise ContractError(f"command timed out after {timeout}s: {command}") from exc
    except OSError as exc:
        command = " ".join(str(value) for value in args[:3])
        raise ContractError(f"cannot execute command: {command}: {exc}") from exc
    result = CommandResult(tuple(args), completed.stdout, completed.stderr, completed.returncode)
    if check and completed.returncode != 0:
        command = " ".join(args[:3])
        detail = completed.stderr.decode("utf-8", "replace").strip()[-800:]
        raise ContractError(f"command failed ({completed.returncode}): {command}: {detail}")
    return result


def require_executable(name: str) -> None:
    from shutil import which

    if which(name) is None:
        raise ContractError(f"required executable is unavailable: {name}")


def require_digest_image(image: str, *, field: str) -> str:
    if not DIGEST_IMAGE_RE.fullmatch(image):
        raise ContractError(f"{field} must be a repository@sha256 digest")
    return image


def require_safe_id(value: str, *, field: str) -> str:
    if not SAFE_ID_RE.fullmatch(value):
        raise ContractError(f"{field} contains unsupported characters")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load JSON contract {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"JSON contract must be an object: {path}")
    return payload


def atomic_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Mapping[str, Any], *, mode: int = 0o600) -> None:
    atomic_write(
        path,
        (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        mode=mode,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_protected_file(path: Path, *, owner_uid: int | None = None) -> None:
    """Require a non-symlink regular file with no group/other permission bits."""
    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError(f"protected file is unavailable: {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ContractError(f"protected path must be a non-symlink regular file: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ContractError(f"protected file permissions must be 0600 or stricter: {path}")
    expected_uid = os.geteuid() if owner_uid is None else owner_uid
    if info.st_uid != expected_uid:
        raise ContractError(f"protected file owner mismatch: {path}")


def parse_remote(value: str) -> tuple[str, str]:
    match = REMOTE_RE.fullmatch(value)
    if not match:
        raise ContractError("remote must be in host:/absolute/path form without whitespace")
    host = match.group("host")
    path = match.group("path").rstrip("/")
    if not path or ".." in Path(path).parts:
        raise ContractError("remote path must be absolute and traversal-free")
    return host, path


def docker_ps_ids(*, project: str, service: str, docker: str = "docker") -> list[str]:
    result = run_command(
        [
            docker,
            "ps",
            "--filter",
            "status=running",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
        ]
    )
    return [line.strip() for line in result.stdout.decode().splitlines() if line.strip()]


def inspect_container(container_id: str, *, docker: str = "docker") -> dict[str, Any]:
    result = run_command([docker, "inspect", container_id])
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ContractError(f"unexpected docker inspect result for {container_id}")
    return payload[0]


def resolve_compose_service(
    *, project: str, service: str, docker: str = "docker"
) -> dict[str, Any]:
    """Resolve exactly one running container by stable Compose labels."""
    require_safe_id(project, field="compose project")
    require_safe_id(service, field="compose service")
    ids = docker_ps_ids(project=project, service=service, docker=docker)
    if len(ids) != 1:
        raise ContractError(
            f"expected exactly one running container for {project}/{service}; found {len(ids)}"
        )
    inspected = inspect_container(ids[0], docker=docker)
    labels = inspected.get("Config", {}).get("Labels") or {}
    if labels.get("com.docker.compose.project") != project:
        raise ContractError(f"compose project label mismatch for {project}/{service}")
    if labels.get("com.docker.compose.service") != service:
        raise ContractError(f"compose service label mismatch for {project}/{service}")
    state = inspected.get("State") or {}
    if not state.get("Running") or state.get("Status") != "running":
        raise ContractError(f"resolved container is not running: {project}/{service}")
    return inspected


def resolve_compose_volume(
    *, project: str, volume: str, docker: str = "docker"
) -> dict[str, Any]:
    require_safe_id(project, field="compose project")
    require_safe_id(volume, field="compose volume")
    result = run_command(
        [
            docker,
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.volume={volume}",
            "--format",
            "{{.Name}}",
        ]
    )
    names = [line.strip() for line in result.stdout.decode().splitlines() if line.strip()]
    if len(names) != 1:
        raise ContractError(
            f"expected exactly one volume for {project}/{volume}; found {len(names)}"
        )
    inspected_result = run_command([docker, "volume", "inspect", names[0]])
    payload = json.loads(inspected_result.stdout)
    if not isinstance(payload, list) or len(payload) != 1:
        raise ContractError(f"unexpected volume inspect result for {project}/{volume}")
    inspected = payload[0]
    labels = inspected.get("Labels") or {}
    if labels.get("com.docker.compose.project") != project:
        raise ContractError(f"volume project label mismatch for {project}/{volume}")
    if labels.get("com.docker.compose.volume") != volume:
        raise ContractError(f"volume label mismatch for {project}/{volume}")
    return inspected


def container_identity(inspected: Mapping[str, Any]) -> dict[str, Any]:
    config = inspected.get("Config") or {}
    labels = config.get("Labels") or {}
    return {
        "container_id": str(inspected.get("Id", "")),
        "container_name": str(inspected.get("Name", "")).lstrip("/"),
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
        "image_reference": config.get("Image"),
        "image_id": inspected.get("Image"),
    }


def find_mount(inspected: Mapping[str, Any], destination: str) -> dict[str, Any]:
    matches = [
        mount
        for mount in inspected.get("Mounts") or []
        if mount.get("Destination") == destination
    ]
    if len(matches) != 1:
        raise ContractError(
            f"expected exactly one mount at {destination}; found {len(matches)}"
        )
    return matches[0]


def safe_member_name(value: str) -> str:
    return require_safe_id(value.replace("/", "-"), field="archive member id")


def ensure_within(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    root = parent.resolve()
    if root != resolved and root not in resolved.parents:
        raise ContractError(f"path escapes expected root: {path}")


def safe_extract_tar(archive: Path, destination: Path) -> None:
    """Extract regular files/directories without trusting tar paths or modes."""
    import shutil
    import tarfile
    from pathlib import PurePosixPath

    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    seen: set[str] = set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            posix = PurePosixPath(member.name)
            if not member.name or posix.is_absolute() or ".." in posix.parts:
                raise ContractError(f"unsafe archive member name: {member.name!r}")
            parts = tuple(part for part in posix.parts if part not in ("", "."))
            if not parts:
                if member.isdir():
                    continue
                raise ContractError(f"unsafe archive member name: {member.name!r}")
            normalized = PurePosixPath(*parts).as_posix()
            if normalized in seen:
                raise ContractError(f"duplicate archive member: {normalized}")
            seen.add(normalized)
            target = destination.joinpath(*parts)
            ensure_within(target, destination)
            if member.isdir():
                if target.exists() and not target.is_dir():
                    raise ContractError(f"archive member type collision: {normalized}")
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(target, 0o700)
                continue
            if not member.isreg():
                raise ContractError(f"unsupported archive member type: {normalized}")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            ensure_within(target.parent, destination)
            source = tar.extractfile(member)
            if source is None:
                raise ContractError(f"cannot read archive member: {normalized}")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(target, flags, 0o600)
            except OSError as exc:
                raise ContractError(
                    f"cannot create extracted archive member {normalized}: {exc}"
                ) from exc
            with source, os.fdopen(descriptor, "wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())


def write_prometheus_textfile(path: Path, lines: Iterable[str]) -> None:
    content = "\n".join(line.rstrip("\n") for line in lines) + "\n"
    atomic_write(path, content.encode("utf-8"), mode=0o644)
