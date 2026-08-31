#!/usr/bin/python3
"""Security primitives shared by the Klyrow production validator.

This module deliberately contains no Docker or application mutation primitive.
All external commands are fixed argv vectors selected by the root helper.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


VERSION = "1.0.0"
EXPECTED_RUNBOOK_SHA256 = (
    "bb00db22a331aac10510f4e07ad7b31b590960b4501f705297a5b286d195b9ae"
)
RUNBOOK_PATH = Path(
    "/root/STAGE6-STAGE8-BLOCKER-REMEDIATION-20260831-authenticated-bb00db22.md"
)
SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
APPROVED_ACTIONS = (
    "authenticate-runbook",
    "inventory",
    "configuration-readback",
    "release-identity",
    "health",
    "authorization-tests",
    "no-effect-tests",
    "callback-tests",
    "smtp-no-data",
    "collect-evidence",
    "status",
)

SSH_COMMAND_RE = re.compile(
    r"\Aklyrow-production-validator (" + "|".join(APPROVED_ACTIONS) + r")\Z"
)
CORRELATION_RE = re.compile(r"\Akpv-[0-9a-f]{32}\Z")
IP_RE = re.compile(r"\A[0-9A-Fa-f:.]{2,45}\Z")
SECRET_KEY_RE = re.compile(
    r"(?i)(authorization|cookie|password|passwd|token|api[_-]?key|client[_-]?secret|"
    r"smtp[_-]?(password|credential)|private[_-]?key|database[_-]?(url|dsn))"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|cookie|password|passwd|token|api[_-]?key|client[_-]?secret|"
    r"smtp[_-]?(?:password|credential)|private[_-]?key|database[_-]?(?:url|dsn))"
    r"\s*[:=]\s*([^\s,;]+)"
)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----.*?"
    r"-----END (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----",
    re.DOTALL,
)


class PolicyError(RuntimeError):
    """A fail-closed policy violation."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed_ms: int
    truncated: bool
    timed_out: bool


def parse_direct(argv: Sequence[str]) -> str:
    if len(argv) != 1 or argv[0] not in APPROVED_ACTIONS:
        raise PolicyError("COMMAND_REJECTED")
    return argv[0]


def parse_ssh_original_command(value: str | None) -> str:
    if value is None or "\x00" in value or "\r" in value or "\n" in value:
        raise PolicyError("SSH_COMMAND_REJECTED")
    match = SSH_COMMAND_RE.fullmatch(value)
    if match is None:
        raise PolicyError("SSH_COMMAND_REJECTED")
    return match.group(1)


def sanitized_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    if extra:
        for key, value in extra.items():
            if key not in {"KPV_CORRELATION_ID", "KPV_SOURCE_ADDRESS"}:
                raise PolicyError("ENVIRONMENT_REJECTED")
            if key == "KPV_CORRELATION_ID" and not CORRELATION_RE.fullmatch(value):
                raise PolicyError("CORRELATION_ID_REJECTED")
            if key == "KPV_SOURCE_ADDRESS" and not IP_RE.fullmatch(value):
                raise PolicyError("SOURCE_ADDRESS_REJECTED")
            env[key] = value
    return env


def reject_dangerous_environment(env: Mapping[str, str]) -> None:
    forbidden = (
        "LD_",
        "DYLD_",
        "PYTHON",
        "PERL",
        "RUBY",
        "BASH_ENV",
        "ENV",
        "CDPATH",
        "GIT_",
        "DOCKER_",
        "COMPOSE_",
    )
    for key in env:
        if key == "IFS" or key.startswith(forbidden):
            raise PolicyError("ENVIRONMENT_REJECTED")


def redact_text(value: str) -> str:
    value = PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", value)
    value = BEARER_RE.sub("Bearer [REDACTED]", value)
    return SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)


def redact_object(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            redacted[key] = (
                "[REDACTED]" if SECRET_KEY_RE.search(key) else redact_object(raw_value)
            )
        return redacted
    if isinstance(value, list):
        return [redact_object(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def regular_nonsymlink(path: Path, *, allowed_owners: Iterable[int] = (0,)) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise PolicyError(f"MISSING_FILE:{path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PolicyError(f"UNSAFE_FILE_TYPE:{path}")
    if metadata.st_uid not in set(allowed_owners):
        raise PolicyError(f"UNSAFE_FILE_OWNER:{path}")
    if metadata.st_mode & 0o022:
        raise PolicyError(f"UNSAFE_FILE_MODE:{path}")
    return metadata


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(fd, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def secure_directory(path: Path, *, mode: int = 0o700, owner_uid: int | None = None) -> None:
    if not path.is_absolute():
        raise PolicyError("DIRECTORY_PATH_REJECTED")
    expected_owner = os.geteuid() if owner_uid is None else owner_uid
    current = Path("/")
    for component in path.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            os.mkdir(current, mode)
            metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise PolicyError(f"UNSAFE_DIRECTORY_TYPE:{current}")
        permissions = metadata.st_mode & 0o7777
        sticky_root_directory = metadata.st_uid == 0 and permissions & stat.S_ISVTX
        trusted_root_ancestor = metadata.st_uid == 0 and (
            not permissions & 0o022 or sticky_root_directory
        )
        if metadata.st_uid != expected_owner and not trusted_root_ancestor:
            raise PolicyError(f"UNSAFE_DIRECTORY_OWNER:{current}")
        if permissions & 0o022 and not sticky_root_directory:
            raise PolicyError(f"UNSAFE_DIRECTORY_MODE:{current}")


def safe_json_file(
    path: Path,
    *,
    allowed_keys: set[str],
    maximum_bytes: int = 65536,
    allowed_owners: Iterable[int] = (0,),
) -> dict[str, object]:
    metadata = regular_nonsymlink(path, allowed_owners=allowed_owners)
    if metadata.st_size > maximum_bytes:
        raise PolicyError(f"FILE_TOO_LARGE:{path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, maximum_bytes + 1)
    finally:
        os.close(fd)
    if len(raw) > maximum_bytes:
        raise PolicyError(f"FILE_TOO_LARGE:{path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"INVALID_JSON:{path}") from exc
    if not isinstance(value, dict) or not set(value).issubset(allowed_keys):
        raise PolicyError(f"JSON_SCHEMA_REJECTED:{path}")
    if any(SECRET_KEY_RE.search(str(key)) for key in value):
        raise PolicyError(f"SECRET_FIELD_REJECTED:{path}")
    return value


def limited_command(
    argv: Sequence[str],
    *,
    timeout_seconds: int,
    maximum_output_bytes: int,
) -> CommandResult:
    if not argv or not os.path.isabs(argv[0]):
        raise PolicyError("NON_ABSOLUTE_EXECUTABLE")
    if timeout_seconds < 1 or maximum_output_bytes < 1:
        raise PolicyError("INVALID_EXECUTION_LIMIT")
    started = time.monotonic()
    process = subprocess.Popen(
        tuple(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=sanitized_environment(),
        close_fds=True,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    observed_bytes = 0
    timed_out = False
    while selector.get_map():
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            break
        for key, _ in selector.select(timeout=min(remaining, 0.1)):
            chunk = os.read(key.fd, 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            observed_bytes += len(chunk)
            available = max(0, maximum_output_bytes - sum(map(len, buffers.values())))
            if available:
                buffers[key.data].extend(chunk[:available])
    selector.close()
    if process.poll() is None:
        process.wait(timeout=2)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    decode = lambda raw: redact_text(raw.decode("utf-8", errors="replace"))
    return CommandResult(
        argv=tuple(argv),
        returncode=124 if timed_out else int(process.returncode),
        stdout=decode(buffers["stdout"]),
        stderr=decode(buffers["stderr"]),
        elapsed_ms=elapsed_ms,
        truncated=observed_bytes > maximum_output_bytes,
        timed_out=timed_out,
    )


class ExclusiveLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> "ExclusiveLock":
        secure_directory(self.path.parent)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.fd)
            self.fd = None
            raise PolicyError("OPERATOR_BUSY") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def append_audit(path: Path, record: Mapping[str, object]) -> None:
    secure_directory(path.parent)
    payload = json.dumps(redact_object(dict(record)), sort_keys=True, separators=(",", ":"))
    if len(payload.encode("utf-8")) > 16384:
        raise PolicyError("AUDIT_RECORD_TOO_LARGE")
    fd = os.open(
        path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(fd, payload.encode("utf-8") + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)
