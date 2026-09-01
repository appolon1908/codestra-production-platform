#!/usr/bin/python3
"""Transactionally install or roll back the additive provider-host audit rules."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Callable


RULE_NAME = "60-codestra-provider-host.rules"
RULE_TARGET = Path("/etc/audit/rules.d") / RULE_NAME
AGGREGATE_TARGET = Path("/etc/audit/audit.rules")
STATE_ROOT = Path("/var/lib/codestra/host-auditd")
INSTALLATION_RECORD = STATE_ROOT / "installation.json"
BACKUP_ROOT = Path("/var/backups/codestra-operations/host-auditd")
VALIDATOR_TARGET = Path("/usr/local/sbin/validate-codestra-provider-host-auditd")
VALIDATOR_LAUNCHER_TARGET = Path(
    "/usr/local/sbin/validate-codestra-provider-host-auditd-verified"
)
RELEASE_TRUST_ROOT = Path("/etc/codestra/release")
ALLOWED_SIGNERS_AUTHORITY = RELEASE_TRUST_ROOT / "allowed_signers"
SIGNER_FINGERPRINT_AUTHORITY = RELEASE_TRUST_ROOT / "allowed_signers.ssh-fingerprint"
PYTHON_INTERPRETER = Path("/usr/bin/python3")
COMMAND_MAX_BYTES = 64 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
STAMP_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
CHANGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
APPROVER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{1,127}$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
MANIFEST_LINE_RE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]{0,255})$")
ALLOWED_SIGNER_TYPES = {"ssh-ed25519", "ecdsa-sha2-nistp256", "sk-ssh-ed25519@openssh.com"}
ROOT_AUTHORITY_PATHS = (
    Path("/etc/ssh"),
    Path("/etc/sudoers"),
    Path("/etc/sudoers.d"),
    Path("/etc/audit"),
    Path("/etc/audit/rules.d"),
    RELEASE_TRUST_ROOT,
    Path("/usr/local"),
    Path("/usr/local/sbin"),
    Path("/opt/codestra"),
    Path("/var/lib/codestra"),
)
OPERATOR_HOME = Path("/home/codestra-admin")
COMMANDS = {
    "auditctl": Path("/usr/sbin/auditctl"),
    "augenrules": Path("/usr/sbin/augenrules"),
    "ausearch": Path("/usr/sbin/ausearch"),
    "dpkg-query": Path("/usr/bin/dpkg-query"),
    "service": Path("/usr/sbin/service"),
    "ssh-keygen": Path("/usr/bin/ssh-keygen"),
    "systemctl": Path("/usr/bin/systemctl"),
}
ARCHIVE_MEMBERS = {
    "installer": "codestra/operations/host-auditd/install-provider-host-auditd.py",
    "rules": f"codestra/operations/host-auditd/{RULE_NAME}",
    "validator": "codestra/operations/host-auditd/validate-provider-host-auditd.py",
}
SNAPSHOT_NAMES = {
    RULE_TARGET: "rules.managed",
    AGGREGATE_TARGET: "rules.aggregate",
    VALIDATOR_TARGET: "validator.installed",
    VALIDATOR_LAUNCHER_TARGET: "validator.launcher",
    INSTALLATION_RECORD: "installation.record",
}
ROLLBACK_RESULT_NAME = "rollback-result.json"
ROLLBACK_MUTATION_SCOPE = (
    str(RULE_TARGET),
    str(AGGREGATE_TARGET),
    str(VALIDATOR_TARGET),
    str(VALIDATOR_LAUNCHER_TARGET),
    str(INSTALLATION_RECORD),
    "auditd.service-state",
)


class InstallError(RuntimeError):
    pass


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp_now() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validator_launcher_bytes(
    validator_bytes: bytes,
    source_sha: str,
    validator_target: Path = VALIDATOR_TARGET,
    authority_root: Path = Path("/"),
) -> bytes:
    if SHA_RE.fullmatch(source_sha) is None:
        raise InstallError("launcher source SHA rejected")
    if (
        not authority_root.is_absolute()
        or not validator_target.is_absolute()
        or (
            validator_target != authority_root
            and authority_root not in validator_target.parents
        )
    ):
        raise InstallError("launcher authority root rejected")
    expected_digest = sha256_bytes(validator_bytes)
    python_target, python_digest = python_runtime_identity()
    source = f'''#!/usr/bin/python3 -I
from __future__ import annotations

import hashlib
import os
import pwd
import stat
import sys
from pathlib import Path

VALIDATOR = Path({str(validator_target)!r})
AUTHORITY_ROOT = Path({str(authority_root)!r})
PYTHON_ALIAS = Path({str(PYTHON_INTERPRETER)!r})
PYTHON_TARGET = Path({str(python_target)!r})
EXPECTED_SOURCE_SHA = {source_sha!r}
EXPECTED_VALIDATOR_SHA256 = {expected_digest!r}
EXPECTED_PYTHON_SHA256 = {python_digest!r}
MAX_VALIDATOR_BYTES = 2 * 1024 * 1024
MAX_PYTHON_BYTES = 64 * 1024 * 1024


def fail() -> None:
    print("HOST_AUDITD_LAUNCH=FAIL", file=sys.stderr)
    raise SystemExit(1)


if sys.argv[1:] != ["--expected-source-sha", EXPECTED_SOURCE_SHA]:
    fail()

launcher = Path(__file__).absolute()
if AUTHORITY_ROOT not in launcher.parents or AUTHORITY_ROOT not in VALIDATOR.parents:
    fail()
try:
    if (
        PYTHON_ALIAS.resolve(strict=True) != PYTHON_TARGET
        or Path("/proc/self/exe").resolve(strict=True) != PYTHON_TARGET
    ):
        fail()
    alias_info = PYTHON_ALIAS.lstat()
    if (
        not (stat.S_ISLNK(alias_info.st_mode) or stat.S_ISREG(alias_info.st_mode))
        or alias_info.st_uid != 0
        or alias_info.st_gid != 0
    ):
        fail()
except OSError:
    fail()


def authority_chain(path: Path, root: Path) -> set[Path]:
    result = {{path}}
    cursor = path
    while cursor != root:
        parent = cursor.parent
        if parent == cursor or (
            parent != root and root not in parent.parents
        ):
            fail()
        result.add(parent)
        cursor = parent
    return result


file_authorities = {{launcher, VALIDATOR, PYTHON_TARGET}}
authorities = (
    authority_chain(launcher, AUTHORITY_ROOT)
    | authority_chain(VALIDATOR, AUTHORITY_ROOT)
    | authority_chain(PYTHON_ALIAS.parent, Path("/"))
    | authority_chain(PYTHON_TARGET, Path("/"))
)
for authority in sorted(authorities, key=lambda item: (len(item.parts), str(item))):
    try:
        info = authority.lstat()
    except OSError:
        fail()
    expected_type = stat.S_ISREG if authority in file_authorities else stat.S_ISDIR
    if (
        stat.S_ISLNK(info.st_mode)
        or not expected_type(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        fail()


def identity_can_write(path: Path) -> bool:
    try:
        account = pwd.getpwnam("codestra-admin")
        groups = os.getgrouplist(account.pw_name, account.pw_gid)
        child = os.fork()
    except (KeyError, OSError):
        fail()
    if child == 0:
        try:
            os.setgroups(groups)
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            os._exit(0 if os.access(path, os.W_OK) else 1)
        except BaseException:
            os._exit(2)
    try:
        waited, status = os.waitpid(child, 0)
    except OSError:
        fail()
    if waited != child or not os.WIFEXITED(status):
        fail()
    result = os.WEXITSTATUS(status)
    if result not in {{0, 1}}:
        fail()
    return result == 0


if any(identity_can_write(authority) for authority in authorities):
    fail()


def exact_digest(path: Path, maximum: int) -> str:
    try:
        file_descriptor = os.open(
            path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        )
    except OSError:
        fail()
    try:
        file_info = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(file_info.st_mode)
            or file_info.st_uid != 0
            or file_info.st_gid != 0
            or stat.S_IMODE(file_info.st_mode) & 0o022
            or file_info.st_size <= 0
            or file_info.st_size > maximum
        ):
            fail()
        chunks = []
        remaining = maximum + 1
        while remaining:
            block = os.read(file_descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        payload = b"".join(chunks)
        if len(payload) != file_info.st_size:
            fail()
        return hashlib.sha256(payload).hexdigest()
    finally:
        os.close(file_descriptor)


if exact_digest(PYTHON_TARGET, MAX_PYTHON_BYTES) != EXPECTED_PYTHON_SHA256:
    fail()

try:
    descriptor = os.open(VALIDATOR, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
except OSError:
    fail()
try:
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) & 0o022
        or info.st_size <= 0
        or info.st_size > MAX_VALIDATOR_BYTES
    ):
        fail()
    chunks = []
    remaining = MAX_VALIDATOR_BYTES + 1
    while remaining:
        block = os.read(descriptor, min(1024 * 1024, remaining))
        if not block:
            break
        chunks.append(block)
        remaining -= len(block)
    payload = b"".join(chunks)
    if (
        len(payload) != info.st_size
        or hashlib.sha256(payload).hexdigest() != EXPECTED_VALIDATOR_SHA256
    ):
        fail()
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.set_inheritable(descriptor, True)
    os.execve(
        str(PYTHON_TARGET),
        [
            str(PYTHON_TARGET),
            "-I",
            f"/proc/self/fd/{{descriptor}}",
            "--expected-source-sha",
            EXPECTED_SOURCE_SHA,
        ],
        {{"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}},
    )
finally:
    os.close(descriptor)
'''
    return source.encode("utf-8")


def checked_regular_snapshot(
    path: Path, *, max_bytes: int = 1024 * 1024
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise InstallError(f"non-regular file rejected: {path}")
        if info.st_size > max_bytes:
            raise InstallError(f"oversized file rejected: {path}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        value = b"".join(chunks)
        if len(value) > max_bytes:
            raise InstallError(f"oversized file rejected: {path}")
        return value, info
    finally:
        os.close(descriptor)


def checked_regular(path: Path, *, max_bytes: int = 1024 * 1024) -> bytes:
    return checked_regular_snapshot(path, max_bytes=max_bytes)[0]


def checked_root_regular(path: Path, *, max_bytes: int = 1024 * 1024) -> bytes:
    value, info = checked_regular_snapshot(path, max_bytes=max_bytes)
    if info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise InstallError(f"unsafe root trust authority: {path}")
    return value


def checked_root_regular_exact(
    path: Path, mode: int, *, max_bytes: int = 1024 * 1024
) -> bytes:
    value, info = checked_regular_snapshot(path, max_bytes=max_bytes)
    if (
        info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != mode
    ):
        raise InstallError(f"unsafe exact root metadata: {path}")
    return value


def python_runtime_identity() -> tuple[Path, str]:
    """Bind the fixed shebang alias to one protected root-owned interpreter."""

    if not PYTHON_INTERPRETER.is_absolute():
        raise InstallError("Python interpreter alias rejected")
    try:
        alias_info = PYTHON_INTERPRETER.lstat()
        resolved = PYTHON_INTERPRETER.resolve(strict=True)
    except OSError as exc:
        raise InstallError("Python interpreter authority unavailable") from exc
    if (
        not (stat.S_ISLNK(alias_info.st_mode) or stat.S_ISREG(alias_info.st_mode))
        or alias_info.st_uid != 0
        or alias_info.st_gid != 0
        or not resolved.is_absolute()
    ):
        raise InstallError("Python interpreter alias rejected")
    value, info = checked_regular_snapshot(resolved, max_bytes=64 * 1024 * 1024)
    if (
        info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) & 0o022
        or stat.S_IMODE(info.st_mode) & 0o111 == 0
        or not value
    ):
        raise InstallError("Python interpreter target rejected")
    return resolved, sha256_bytes(value)


def command_runtime_identities() -> dict[str, tuple[Path, str]]:
    """Authenticate every fixed privileged helper before invoking any helper."""

    identities: dict[str, tuple[Path, str]] = {}
    for name, path in COMMANDS.items():
        if not path.is_absolute():
            raise InstallError(f"required audit command path rejected: {name}")
        try:
            alias_info = path.lstat()
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise InstallError(f"required audit command missing: {name}") from exc
        if (
            not stat.S_ISREG(alias_info.st_mode)
            or alias_info.st_uid != 0
            or alias_info.st_gid != 0
            or stat.S_IMODE(alias_info.st_mode) & 0o022
            or not resolved.is_absolute()
            or resolved != path
        ):
            raise InstallError(f"required audit command authority rejected: {name}")
        value, info = checked_regular_snapshot(resolved, max_bytes=COMMAND_MAX_BYTES)
        if (
            info.st_uid != 0
            or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
            or stat.S_IMODE(info.st_mode) & 0o111 == 0
            or not value
        ):
            raise InstallError(f"required audit command target rejected: {name}")
        identities[name] = (resolved, sha256_bytes(value))
    return identities


def write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise InstallError("short write rejected")
        view = view[written:]


def atomic_write(path: Path, value: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise InstallError(f"symlink target rejected: {path}")
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        mode,
    )
    try:
        write_all(descriptor, value)
        os.fchmod(descriptor, mode)
        os.fchown(descriptor, 0, 0)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def secure_directory(path: Path, mode: int = 0o700) -> None:
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if cursor.is_symlink() or not cursor.is_dir():
        raise InstallError(f"unsafe directory ancestor: {cursor}")
    for directory in reversed(missing):
        directory.mkdir(mode=mode)
        os.chown(directory, 0, 0)
        os.chmod(directory, mode)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0:
        raise InstallError(f"unsafe root directory: {path}")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise InstallError(f"writable root directory rejected: {path}")


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )


def run_checked_bytes(command: list[str], input_bytes: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        check=True,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )


def command_output(command: list[str]) -> str:
    return run_checked(command).stdout


def identity_can_write(path: Path, account: pwd.struct_passwd) -> bool:
    """Evaluate effective write access after irreversibly dropping a child UID."""

    groups = os.getgrouplist(account.pw_name, account.pw_gid)
    child = os.fork()
    if child == 0:
        try:
            os.setgroups(groups)
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            os._exit(0 if os.access(path, os.W_OK) else 1)
        except BaseException:
            os._exit(2)
    waited, status = os.waitpid(child, 0)
    if waited != child or not os.WIFEXITED(status):
        raise InstallError("operator writability child failed")
    result = os.WEXITSTATUS(status)
    if result not in {0, 1}:
        raise InstallError("operator writability check failed")
    return result == 0


def operator_cannot_modify(paths: list[Path], *, allow_missing: bool = False) -> bool:
    account = pwd.getpwnam("codestra-admin")
    for path in paths:
        try:
            info = path.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            return False
        if stat.S_ISLNK(info.st_mode):
            return False
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid == account.pw_uid and mode & 0o200:
            return False
        if info.st_gid == account.pw_gid and mode & 0o020:
            return False
        if mode & 0o002:
            return False
        if identity_can_write(path, account):
            return False
    return True


def path_authority_chain(paths: list[Path]) -> list[Path]:
    authorities: set[Path] = set()
    for path in paths:
        if not path.is_absolute():
            raise InstallError("validator authority path must be absolute")
        cursor = path
        while True:
            authorities.add(cursor)
            if cursor == Path("/"):
                break
            cursor = cursor.parent
    return sorted(authorities, key=lambda item: (len(item.parts), str(item)))


def snapshot_release_inputs(args: argparse.Namespace) -> tuple[Path, dict[str, Path], dict[str, str]]:
    root_home = Path(pwd.getpwnam("root").pw_dir)
    root_home_info = root_home.lstat()
    if (
        not stat.S_ISDIR(root_home_info.st_mode)
        or root_home_info.st_uid != 0
        or root_home_info.st_gid != 0
        or stat.S_IMODE(root_home_info.st_mode) & 0o022
    ):
        raise InstallError("unsafe root staging authority")
    stage = Path(
        tempfile.mkdtemp(prefix="codestra-host-auditd.", dir=str(root_home))
    )
    os.chown(stage, 0, 0)
    os.chmod(stage, 0o700)
    sources = {
        "archive": (Path(args.release_archive), 128 * 1024 * 1024, False),
        "deployment": (Path(args.release_manifest), 1024 * 1024, False),
        "checksums": (Path(args.release_checksums), 1024 * 1024, False),
        "signature": (Path(args.release_signature), 64 * 1024, False),
        "allowed_signers": (ALLOWED_SIGNERS_AUTHORITY, 64 * 1024, True),
        "signer_fingerprint": (SIGNER_FINGERPRINT_AUTHORITY, 256, True),
    }
    staged: dict[str, Path] = {}
    digests: dict[str, str] = {}
    identities: set[tuple[int, int]] = set()
    try:
        for label, (source, limit, root_authority) in sources.items():
            value, info = checked_regular_snapshot(source, max_bytes=limit)
            if root_authority and (
                info.st_uid != 0
                or info.st_gid != 0
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                raise InstallError(f"unsafe root trust authority: {source}")
            identity = (info.st_dev, info.st_ino)
            if identity in identities:
                raise InstallError("release input aliases another input")
            identities.add(identity)
            target = stage / label
            atomic_write(target, value, 0o600)
            staged[label] = target
            digests[label] = sha256_bytes(value)
        return stage, staged, digests
    except BaseException:
        shutil.rmtree(stage)
        raise


def parse_release_checksums(value: bytes) -> dict[str, str]:
    try:
        lines = value.decode("ascii", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise InstallError("release checksums encoding rejected") from exc
    result: dict[str, str] = {}
    for line in lines:
        match = MANIFEST_LINE_RE.fullmatch(line)
        if match is None or match.group(2) in result:
            raise InstallError("release checksums format rejected")
        result[match.group(2)] = match.group(1)
    if not result:
        raise InstallError("release checksums are empty")
    return result


def signer_fingerprint(allowed_signers: bytes, stage: Path) -> str:
    try:
        lines = allowed_signers.decode("ascii", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise InstallError("allowed-signers encoding rejected") from exc
    if len(lines) != 1:
        raise InstallError("allowed-signers authority must contain exactly one record")
    fields = lines[0].split()
    if (
        len(fields) != 3
        or fields[0] != "codestra-release"
        or fields[1] not in ALLOWED_SIGNER_TYPES
        or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", fields[2])
    ):
        raise InstallError("allowed-signers authority rejected")
    public_key = f"{fields[1]} {fields[2]}\n".encode("ascii")
    public_key_path = stage / "signer.pub"
    atomic_write(public_key_path, public_key, 0o600)
    output = command_output(
        [str(COMMANDS["ssh-keygen"]), "-lf", str(public_key_path), "-E", "sha256"]
    ).split()
    if len(output) < 2 or FINGERPRINT_RE.fullmatch(output[1]) is None:
        raise InstallError("signer fingerprint output rejected")
    return output[1]


def archive_members(archive: bytes) -> dict[str, bytes]:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            members = bundle.getmembers()
            result: dict[str, bytes] = {}
            for label, expected_name in ARCHIVE_MEMBERS.items():
                matches = [member for member in members if member.name == expected_name]
                if len(matches) != 1:
                    raise InstallError(f"signed archive member identity rejected: {label}")
                member = matches[0]
                if not member.isfile() or member.size <= 0 or member.size > 2 * 1024 * 1024:
                    raise InstallError(f"signed archive member type or size rejected: {label}")
                stream = bundle.extractfile(member)
                if stream is None:
                    raise InstallError(f"signed archive member unreadable: {label}")
                value = stream.read(2 * 1024 * 1024 + 1)
                if len(value) != member.size:
                    raise InstallError(f"signed archive member read-back rejected: {label}")
                result[label] = value
            return result
    except (tarfile.TarError, OSError) as exc:
        raise InstallError("signed release archive rejected") from exc


def verify_signed_release(
    args: argparse.Namespace,
    stage: Path,
    staged: dict[str, Path],
    input_digests: dict[str, str],
) -> tuple[bytes, bytes, dict[str, object]]:
    allowed_signers = checked_root_regular(staged["allowed_signers"], max_bytes=64 * 1024)
    fingerprint = signer_fingerprint(allowed_signers, stage)
    fingerprint_authority = checked_root_regular(
        staged["signer_fingerprint"], max_bytes=256
    )
    if fingerprint_authority != f"{fingerprint}\n".encode("ascii"):
        raise InstallError("approved signer fingerprint mismatch")
    checksums_bytes = checked_root_regular(staged["checksums"])
    run_checked_bytes(
        [
            str(COMMANDS["ssh-keygen"]),
            "-Y",
            "verify",
            "-f",
            str(staged["allowed_signers"]),
            "-I",
            "codestra-release",
            "-n",
            "codestra-release",
            "-s",
            str(staged["signature"]),
        ],
        checksums_bytes,
    )
    archive_name = f"codestra-production-platform-{args.source_sha}.tar.gz"
    if Path(args.release_archive).name != archive_name:
        raise InstallError("release archive filename rejected")
    checksums = parse_release_checksums(checksums_bytes)
    if checksums.get(archive_name) != input_digests["archive"]:
        raise InstallError("release archive checksum mismatch")
    if checksums.get("deployment-manifest.json") != input_digests["deployment"]:
        raise InstallError("release deployment manifest checksum mismatch")
    try:
        deployment = json.loads(checked_root_regular(staged["deployment"]))
    except json.JSONDecodeError as exc:
        raise InstallError("release deployment manifest rejected") from exc
    release_tuple = deployment.get("release_tuple")
    if (
        deployment.get("schema_version") != "codestra.deployment.v1"
        or deployment.get("commit") != args.source_sha
        or deployment.get("artifact") != archive_name
        or deployment.get("artifact_sha256") != input_digests["archive"]
        or not isinstance(release_tuple, dict)
        or release_tuple.get("orchestration_repository")
        != "appolon1908-hue/codestra-production-platform"
        or release_tuple.get("orchestration_protected_sha") != args.source_sha
    ):
        raise InstallError("release source identity mismatch")
    archive = checked_root_regular(staged["archive"], max_bytes=128 * 1024 * 1024)
    members = archive_members(archive)
    installer_source = Path(__file__).absolute()
    if installer_source.is_symlink():
        raise InstallError("symlink installer source rejected")
    if checked_regular(installer_source, max_bytes=2 * 1024 * 1024) != members["installer"]:
        raise InstallError("running installer differs from signed release")
    return members["rules"], members["validator"], {
        "release_archive": archive_name,
        "release_archive_sha256": input_digests["archive"],
        "release_manifest_sha256": input_digests["deployment"],
        "release_checksums_sha256": input_digests["checksums"],
        "release_signature_sha256": input_digests["signature"],
        "allowed_signers_sha256": input_digests["allowed_signers"],
        "signer_fingerprint_authority_sha256": input_digests[
            "signer_fingerprint"
        ],
        "signer_fingerprint": fingerprint,
        "signature_verification": "PASS",
    }


def audit_status(run: Callable[[list[str]], str] = command_output) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in run([str(COMMANDS["auditctl"]), "-s"]).splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in {"enabled", "failure", "pid", "rate_limit", "backlog_limit", "lost", "backlog"}:
            try:
                values[fields[0]] = int(fields[1])
            except ValueError as exc:
                raise InstallError("invalid audit kernel status") from exc
    if "enabled" not in values:
        raise InstallError("audit kernel status is incomplete")
    return values


def service_state(run: Callable[[list[str]], str] = command_output) -> dict[str, bool]:
    def matches(argument: str, expected: str) -> bool:
        try:
            return run([str(COMMANDS["systemctl"]), argument, "auditd.service"]).strip() == expected
        except subprocess.CalledProcessError:
            return False

    return {"enabled": matches("is-enabled", "enabled"), "active": matches("is-active", "active")}


def require_prerequisites() -> None:
    if os.geteuid() != 0:
        raise InstallError("installer must run as root")
    os_release = checked_regular(Path("/usr/lib/os-release"), max_bytes=64 * 1024).decode("utf-8", "strict")
    identity = next((line.split("=", 1)[1].strip().strip('"') for line in os_release.splitlines() if line.startswith("ID=")), "")
    if identity not in {"ubuntu", "debian"}:
        raise InstallError("unsupported operating system")
    command_identities = command_runtime_identities()
    command_targets = [identity[0] for identity in command_identities.values()]
    if not operator_cannot_modify(
        path_authority_chain([*COMMANDS.values(), *command_targets])
    ):
        raise InstallError("codestra-admin can modify audit command authority")
    package = command_output([str(COMMANDS["dpkg-query"]), "-W", "-f=${Status}", "auditd"]).strip()
    if package != "install ok installed":
        raise InstallError("distribution auditd package is not installed")
    for path in ROOT_AUTHORITY_PATHS:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise InstallError(f"required host authority path missing: {path}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise InstallError(f"symlink host authority path rejected: {path}")
        expected_type = stat.S_ISREG if path == Path("/etc/sudoers") else stat.S_ISDIR
        if not expected_type(info.st_mode) or info.st_uid != 0 or info.st_gid != 0:
            raise InstallError(f"root host authority path rejected: {path}")
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise InstallError(f"writable host authority path rejected: {path}")
    account = pwd.getpwnam("codestra-admin")
    home_info = OPERATOR_HOME.lstat()
    if (
        not stat.S_ISDIR(home_info.st_mode)
        or home_info.st_uid != account.pw_uid
        or stat.S_IMODE(home_info.st_mode) & 0o022
    ):
        raise InstallError("codestra-admin home authority rejected")
    python_target, _python_digest = python_runtime_identity()
    operator_paths = path_authority_chain(
        [
            *ROOT_AUTHORITY_PATHS,
            ALLOWED_SIGNERS_AUTHORITY,
            SIGNER_FINGERPRINT_AUTHORITY,
            PYTHON_INTERPRETER.parent,
            python_target,
            *COMMANDS.values(),
            *command_targets,
            RULE_TARGET,
            AGGREGATE_TARGET,
            VALIDATOR_TARGET,
            VALIDATOR_LAUNCHER_TARGET,
            INSTALLATION_RECORD,
        ]
    )
    if not operator_cannot_modify(operator_paths, allow_missing=True):
        raise InstallError("codestra-admin can modify host installation authority")


def snapshot_file(path: Path, destination: Path) -> dict[str, object]:
    if path.is_symlink():
        raise InstallError(f"symlink rollback source rejected: {path}")
    if not path.exists():
        return {"path": str(path), "present": False}
    value = checked_regular(path)
    info = path.stat(follow_symlinks=False)
    try:
        copy = destination / SNAPSHOT_NAMES[path]
    except KeyError as exc:
        raise InstallError(f"unsupported rollback target: {path}") from exc
    atomic_write(copy, value, 0o600)
    return {
        "path": str(path),
        "present": True,
        "sha256": sha256_bytes(value),
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "snapshot": copy.name,
    }


def snapshot_before(source_sha: str, state: dict[str, bool]) -> tuple[str, Path, dict[str, object]]:
    stamp = stamp_now()
    secure_directory(BACKUP_ROOT)
    destination = BACKUP_ROOT / stamp
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chown(destination, 0, 0)
    record: dict[str, object] = {
        "schema": "codestra.host-auditd.rollback.v1",
        "stamp": stamp,
        "source_sha": source_sha,
        "service_before": state,
        "files": [
            snapshot_file(RULE_TARGET, destination),
            snapshot_file(AGGREGATE_TARGET, destination),
            snapshot_file(VALIDATOR_TARGET, destination),
            snapshot_file(VALIDATOR_LAUNCHER_TARGET, destination),
            snapshot_file(INSTALLATION_RECORD, destination),
        ],
    }
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    atomic_write(destination / "rollback.json", payload, 0o600)
    atomic_write(
        destination / "SHA256SUMS",
        f"{sha256_bytes(payload)}  rollback.json\n".encode(),
        0o600,
    )
    return stamp, destination, record


def validate_rollback_checkpoint(
    checkpoint: Path,
    expected_source_sha: str,
    expected_stamp: str,
    *,
    allow_completed_result: bool = False,
) -> dict[str, object]:
    """Authenticate one complete root-only checkpoint before any restoration."""

    if (
        SHA_RE.fullmatch(expected_source_sha) is None
        or STAMP_RE.fullmatch(expected_stamp) is None
        or checkpoint != BACKUP_ROOT / expected_stamp
    ):
        raise InstallError("rollback checkpoint identity rejected")
    manifest_path = checkpoint / "rollback.json"
    checksums_path = checkpoint / "SHA256SUMS"
    result_path = checkpoint / ROLLBACK_RESULT_NAME
    try:
        result_info = result_path.lstat()
    except FileNotFoundError:
        result_info = None
    except OSError as exc:
        raise InstallError("rollback result authority read failed") from exc
    if result_info is not None and not allow_completed_result:
        raise InstallError("rollback checkpoint contains unexpected files")
    initial_files = {manifest_path, checksums_path}
    if result_info is not None:
        initial_files.add(result_path)
    initial_paths = path_authority_chain(
        [BACKUP_ROOT, checkpoint, *initial_files]
    )
    for path in initial_paths:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise InstallError("rollback checkpoint authority is incomplete") from exc
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_gid != 0:
            raise InstallError("rollback checkpoint authority rejected")
        if path in initial_files:
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise InstallError("rollback checkpoint file metadata rejected")
        elif not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o022:
            raise InstallError("rollback checkpoint directory metadata rejected")
    if not operator_cannot_modify(initial_paths):
        raise InstallError("codestra-admin can modify rollback checkpoint authority")

    manifest = checked_root_regular_exact(manifest_path, 0o600)
    checksums = checked_root_regular_exact(
        checksums_path, 0o600, max_bytes=4096
    )
    if checksums != f"{sha256_bytes(manifest)}  rollback.json\n".encode("ascii"):
        raise InstallError("rollback manifest checksum mismatch")
    try:
        record = json.loads(manifest)
    except json.JSONDecodeError as exc:
        raise InstallError("rollback manifest JSON rejected") from exc
    if (
        not isinstance(record, dict)
        or set(record) != {"schema", "stamp", "source_sha", "service_before", "files"}
        or record.get("schema") != "codestra.host-auditd.rollback.v1"
        or record.get("stamp") != expected_stamp
        or record.get("source_sha") != expected_source_sha
    ):
        raise InstallError("rollback manifest identity rejected")
    service = record.get("service_before")
    if (
        not isinstance(service, dict)
        or set(service) != {"enabled", "active"}
        or not all(isinstance(service[key], bool) for key in service)
    ):
        raise InstallError("rollback service checkpoint rejected")
    items = record.get("files")
    if not isinstance(items, list) or len(items) != len(SNAPSHOT_NAMES):
        raise InstallError("rollback file set rejected")
    paths: set[Path] = set()
    snapshots: set[Path] = set()
    for item in items:
        if not isinstance(item, dict):
            raise InstallError("rollback manifest file entry rejected")
        target = Path(str(item.get("path")))
        if target not in SNAPSHOT_NAMES or target in paths:
            raise InstallError("rollback target set rejected")
        paths.add(target)
        present = item.get("present")
        if not isinstance(present, bool):
            raise InstallError("rollback target presence rejected")
        if not present:
            if set(item) != {"path", "present"}:
                raise InstallError("absent rollback entry schema rejected")
            continue
        if set(item) != {
            "path",
            "present",
            "sha256",
            "mode",
            "uid",
            "gid",
            "snapshot",
        }:
            raise InstallError("rollback snapshot entry schema rejected")
        digest = item.get("sha256")
        mode = item.get("mode")
        uid = item.get("uid")
        gid = item.get("gid")
        snapshot_name = item.get("snapshot")
        if (
            not isinstance(digest, str)
            or DIGEST_RE.fullmatch(digest) is None
            or not isinstance(mode, int)
            or isinstance(mode, bool)
            or not 0 <= mode <= 0o7777
            or not isinstance(uid, int)
            or isinstance(uid, bool)
            or uid < 0
            or not isinstance(gid, int)
            or isinstance(gid, bool)
            or gid < 0
            or snapshot_name != SNAPSHOT_NAMES[target]
        ):
            raise InstallError("rollback snapshot metadata rejected")
        snapshot = checkpoint / str(snapshot_name)
        if snapshot in snapshots:
            raise InstallError("rollback snapshot alias rejected")
        snapshots.add(snapshot)
    if paths != set(SNAPSHOT_NAMES):
        raise InstallError("rollback target set rejected")
    expected_children = {manifest_path, checksums_path, *snapshots}
    if result_info is not None:
        expected_children.add(result_path)
    try:
        observed_children = set(checkpoint.iterdir())
    except OSError as exc:
        raise InstallError("rollback checkpoint listing failed") from exc
    if observed_children != expected_children:
        raise InstallError("rollback checkpoint contains unexpected files")
    snapshot_authorities = path_authority_chain(list(snapshots))
    if not operator_cannot_modify(snapshot_authorities):
        raise InstallError("codestra-admin can modify rollback snapshots")
    for item in items:
        if item.get("present") is not True:
            continue
        snapshot = checkpoint / str(item["snapshot"])
        value = checked_root_regular_exact(snapshot, 0o600)
        if sha256_bytes(value) != item["sha256"]:
            raise InstallError("rollback snapshot checksum mismatch")
    return record


def completed_rollback_result(
    checkpoint: Path, expected_source_sha: str, expected_stamp: str
) -> dict[str, object] | None:
    """Return one authenticated completed rollback without repeating mutation."""

    result_path = checkpoint / ROLLBACK_RESULT_NAME
    try:
        result_path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstallError("rollback result authority read failed") from exc
    checkpoint_record = validate_rollback_checkpoint(
        checkpoint,
        expected_source_sha,
        expected_stamp,
        allow_completed_result=True,
    )
    payload = checked_root_regular_exact(result_path, 0o600)
    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InstallError("rollback result JSON rejected") from exc
    if (
        not isinstance(result, dict)
        or set(result)
        != {
            "schema",
            "source_sha",
            "rollback_stamp",
            "completed_at_utc",
            "restored",
            "mutation_scope",
        }
        or result.get("schema") != "codestra.host-auditd.rollback-result.v1"
        or result.get("source_sha") != expected_source_sha
        or result.get("rollback_stamp") != expected_stamp
        or result.get("mutation_scope") != list(ROLLBACK_MUTATION_SCOPE)
    ):
        raise InstallError("rollback result identity rejected")
    completed_at = result.get("completed_at_utc")
    if not isinstance(completed_at, str) or not completed_at.endswith("Z"):
        raise InstallError("rollback result timestamp rejected")
    try:
        parsed_time = dt.datetime.fromisoformat(completed_at[:-1] + "+00:00")
    except ValueError as exc:
        raise InstallError("rollback result timestamp rejected") from exc
    if parsed_time.tzinfo != dt.timezone.utc:
        raise InstallError("rollback result timestamp rejected")
    observed = restored_checkpoint_evidence(checkpoint_record)
    if result.get("restored") != observed:
        raise InstallError("rollback result read-back differs from checkpoint")
    return result


def managed_keys(value: str) -> set[str]:
    keys: set[str] = set()
    for line in value.splitlines():
        match = re.search(r"(?:-k\s+|-F\s+key=)([A-Za-z0-9_.-]+)", line)
        if match:
            keys.add(match.group(1))
    return keys


def require_additive_rules(rule_bytes: bytes) -> None:
    try:
        lines = rule_bytes.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise InstallError("managed rule encoding rejected") from exc
    try:
        for line in lines:
            tokens = shlex.split(line.partition("#")[0].strip())
            if tokens and tokens[0] in {"-D", "-e"}:
                raise InstallError("managed rules may not flush or change global policy")
    except ValueError as exc:
        raise InstallError("managed rule syntax rejected") from exc


def managed_rule_signatures(value: str, keys: set[str]) -> set[tuple[object, ...]]:
    signatures: set[tuple[object, ...]] = set()
    for line in value.splitlines():
        candidate = line.partition("#")[0].strip()
        if not candidate:
            continue
        tokens = shlex.split(candidate)
        key: str | None = None
        if "-k" in tokens:
            index = tokens.index("-k")
            if index + 1 < len(tokens):
                key = tokens[index + 1]
        for index, token in enumerate(tokens):
            if token == "-F" and index + 1 < len(tokens) and tokens[index + 1].startswith("key="):
                key = tokens[index + 1].split("=", 1)[1]
        if key not in keys:
            continue
        if "-w" in tokens:
            watch = tokens[tokens.index("-w") + 1]
            permissions = "".join(sorted(tokens[tokens.index("-p") + 1]))
            signatures.add(("watch", watch, permissions, key))
            continue
        action = tokens[tokens.index("-a") + 1] if "-a" in tokens else ""
        syscalls: set[str] = set()
        filters: set[str] = set()
        for index, token in enumerate(tokens):
            if token == "-S" and index + 1 < len(tokens):
                syscalls.update(tokens[index + 1].split(","))
            elif token == "-F" and index + 1 < len(tokens):
                item = tokens[index + 1]
                if item.startswith("key="):
                    continue
                item = item.replace("arch=c000003e", "arch=b64").replace("arch=40000003", "arch=b32")
                item = item.replace("auid!=unset", "auid!=4294967295")
                item = item.replace("auid=unset", "auid=4294967295")
                filters.add(item)
        signatures.add(("syscall", action, tuple(sorted(syscalls)), tuple(sorted(filters)), key))
    return signatures


def installed_payloads(
    rule_bytes: bytes, validator_bytes: bytes, launcher_bytes: bytes
) -> dict[str, str]:
    installed_rule = checked_root_regular(RULE_TARGET)
    installed_validator = checked_root_regular(
        VALIDATOR_TARGET, max_bytes=2 * 1024 * 1024
    )
    installed_launcher = checked_root_regular(
        VALIDATOR_LAUNCHER_TARGET, max_bytes=2 * 1024 * 1024
    )
    if installed_rule != rule_bytes:
        raise InstallError("installed managed rule differs from signed release")
    if installed_validator != validator_bytes:
        raise InstallError("installed validator differs from signed release")
    if installed_launcher != launcher_bytes:
        raise InstallError("installed validator launcher differs from expected bytes")
    return {
        "managed_rule_sha256": sha256_bytes(installed_rule),
        "validator_sha256": sha256_bytes(installed_validator),
        "validator_launcher_sha256": sha256_bytes(installed_launcher),
    }


def validate_live(
    rule_bytes: bytes, validator_bytes: bytes, launcher_bytes: bytes
) -> dict[str, object]:
    status = audit_status()
    if status.get("enabled") not in {1, 2} or status.get("pid", 0) <= 0 or status.get("lost") != 0:
        raise InstallError("audit kernel state failed closed")
    state = service_state()
    if state != {"enabled": True, "active": True}:
        raise InstallError("auditd service is not enabled and active")
    payloads = installed_payloads(rule_bytes, validator_bytes, launcher_bytes)
    expected_keys = managed_keys(rule_bytes.decode("utf-8", "strict"))
    active_rules = command_output([str(COMMANDS["auditctl"]), "-l"])
    active_keys = managed_keys(active_rules)
    if not expected_keys or not expected_keys <= active_keys:
        raise InstallError("managed audit rules are not active")
    expected_signatures = managed_rule_signatures(rule_bytes.decode("utf-8", "strict"), expected_keys)
    active_signatures = managed_rule_signatures(active_rules, expected_keys)
    if expected_signatures != active_signatures:
        raise InstallError("managed audit rule semantics differ from source")
    return {
        "service": "enabled-active",
        "kernel_enabled": status["enabled"],
        "kernel_lost": status["lost"],
        **payloads,
        "managed_keys": sorted(expected_keys),
    }


def restore_file(record: dict[str, object], checkpoint: Path) -> None:
    target = Path(str(record["path"]))
    if record.get("present") is False:
        if target.is_symlink():
            raise InstallError(f"rollback target type rejected: {target}")
        if target.exists():
            if not target.is_file():
                raise InstallError(f"rollback target type rejected: {target}")
            target.unlink()
        return
    snapshot = checkpoint / str(record["snapshot"])
    value = checked_root_regular_exact(snapshot, 0o600)
    if sha256_bytes(value) != record.get("sha256"):
        raise InstallError("rollback snapshot checksum mismatch")
    atomic_write(target, value, int(record["mode"]))
    os.chown(target, int(record["uid"]), int(record["gid"]), follow_symlinks=False)


def restored_checkpoint_evidence(
    record: dict[str, object],
    read_service_state: Callable[[], dict[str, bool]] = service_state,
) -> dict[str, object]:
    items = record.get("files")
    if not isinstance(items, list):
        raise InstallError("rollback file evidence rejected")
    restored_files: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            raise InstallError("rollback file evidence entry rejected")
        target = Path(str(item["path"]))
        if item.get("present") is False:
            try:
                target.lstat()
            except FileNotFoundError:
                restored_files.append({"path": str(target), "present": False})
                continue
            raise InstallError("absent rollback target was recreated")
        try:
            value, info = checked_regular_snapshot(target)
        except FileNotFoundError:
            raise InstallError("restored target is missing") from None
        digest = sha256_bytes(value)
        if (
            digest != item.get("sha256")
            or stat.S_IMODE(info.st_mode) != item.get("mode")
            or info.st_uid != item.get("uid")
            or info.st_gid != item.get("gid")
        ):
            raise InstallError("restored target read-back differs from checkpoint")
        restored_files.append(
            {"path": str(target), "present": True, "sha256": digest}
        )
    before = record.get("service_before")
    if not isinstance(before, dict):
        raise InstallError("rollback service evidence rejected")
    expected_service = {
        "enabled": before.get("enabled") is True,
        "active": before.get("active") is True,
    }
    observed_service = read_service_state()
    if observed_service != expected_service:
        raise InstallError("restored service state read-back differs from checkpoint")
    return {"files": restored_files, "service": observed_service}


def restore_checkpoint(
    checkpoint: Path, expected_source_sha: str, expected_stamp: str
) -> dict[str, object]:
    record = validate_rollback_checkpoint(
        checkpoint, expected_source_sha, expected_stamp
    )
    items = record.get("files")
    if not isinstance(items, list) or len(items) != len(SNAPSHOT_NAMES):
        raise InstallError("rollback file set rejected")
    paths = {str(item.get("path")) for item in items if isinstance(item, dict)}
    if paths != {str(path) for path in SNAPSHOT_NAMES}:
        raise InstallError("rollback target set rejected")
    for item in items:
        if not isinstance(item, dict):
            raise InstallError("rollback manifest file entry rejected")
        restore_file(item, checkpoint)
    run_checked([str(COMMANDS["augenrules"]), "--load"])
    before = record["service_before"]
    if not isinstance(before, dict):
        raise InstallError("rollback service state rejected")
    if before.get("enabled"):
        run_checked([str(COMMANDS["systemctl"]), "enable", "auditd.service"])
    else:
        run_checked([str(COMMANDS["systemctl"]), "disable", "auditd.service"])
    active = service_state()["active"]
    if before.get("active") and not active:
        run_checked([str(COMMANDS["systemctl"]), "start", "auditd.service"])
    elif not before.get("active") and active:
        run_checked([str(COMMANDS["service"]), "auditd", "stop"])
    return restored_checkpoint_evidence(record)


def persist_installation_record(record: dict[str, object]) -> dict[str, object]:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    atomic_write(INSTALLATION_RECORD, payload, 0o600)
    persisted = checked_root_regular_exact(INSTALLATION_RECORD, 0o600)
    if persisted != payload:
        raise InstallError("installation record read-back differs from written bytes")
    try:
        readback = json.loads(persisted)
    except json.JSONDecodeError as exc:
        raise InstallError("installation record read-back rejected") from exc
    if readback != record:
        raise InstallError("installation record semantic read-back mismatch")
    return readback


def validate_installation_record(
    record: object,
    args: argparse.Namespace,
    release_binding: dict[str, object],
    live: dict[str, object],
) -> dict[str, object]:
    if not isinstance(record, dict) or set(record) != {
        "schema",
        "source_sha",
        "change_id",
        "approver",
        "installed_at_utc",
        "rollback_stamp",
        "rule_sha256",
        "validator_sha256",
        "validator_launcher_sha256",
        "release",
        "state",
    }:
        raise InstallError("installation record schema rejected")
    installed_at = record.get("installed_at_utc")
    if not isinstance(installed_at, str) or not installed_at.endswith("Z"):
        raise InstallError("installation record timestamp rejected")
    try:
        parsed_time = dt.datetime.fromisoformat(installed_at[:-1] + "+00:00")
    except ValueError as exc:
        raise InstallError("installation record timestamp rejected") from exc
    if parsed_time.tzinfo != dt.timezone.utc:
        raise InstallError("installation record timestamp rejected")
    expected = {
        "schema": "codestra.host-auditd.installation.v1",
        "source_sha": args.source_sha,
        "change_id": args.change_id,
        "approver": args.approver,
        "rule_sha256": live["managed_rule_sha256"],
        "validator_sha256": live["validator_sha256"],
        "validator_launcher_sha256": live["validator_launcher_sha256"],
        "release": release_binding,
        "state": live,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise InstallError("installation record binding mismatch")
    rollback_stamp = record.get("rollback_stamp")
    if not isinstance(rollback_stamp, str) or STAMP_RE.fullmatch(rollback_stamp) is None:
        raise InstallError("installation record rollback identity rejected")
    return record


def install(args: argparse.Namespace) -> dict[str, object]:
    require_prerequisites()
    if not SHA_RE.fullmatch(args.source_sha):
        raise InstallError("source SHA rejected")
    if not CHANGE_RE.fullmatch(args.change_id):
        raise InstallError("change ID rejected")
    if not APPROVER_RE.fullmatch(args.approver):
        raise InstallError("approver rejected")
    stage, staged, input_digests = snapshot_release_inputs(args)
    try:
        rule_bytes, validator_bytes, release_binding = verify_signed_release(
            args, stage, staged, input_digests
        )
        launcher_bytes = validator_launcher_bytes(validator_bytes, args.source_sha)
        require_additive_rules(rule_bytes)
        status_before = audit_status()
        if (
            RULE_TARGET.exists()
            and INSTALLATION_RECORD.exists()
            and VALIDATOR_TARGET.exists()
            and VALIDATOR_LAUNCHER_TARGET.exists()
        ):
            existing_record = json.loads(
                checked_root_regular_exact(INSTALLATION_RECORD, 0o600)
            )
            if (
                checked_regular(RULE_TARGET) == rule_bytes
                and checked_regular(VALIDATOR_TARGET) == validator_bytes
                and checked_regular(VALIDATOR_LAUNCHER_TARGET) == launcher_bytes
            ):
                live = validate_live(rule_bytes, validator_bytes, launcher_bytes)
                return validate_installation_record(
                    existing_record, args, release_binding, live
                )
        if status_before["enabled"] == 2:
            raise InstallError("immutable kernel audit policy blocks this exact change")
        before = service_state()
        secure_directory(STATE_ROOT)
        stamp, checkpoint, _rollback_record = snapshot_before(args.source_sha, before)
        validate_rollback_checkpoint(checkpoint, args.source_sha, stamp)
        try:
            atomic_write(RULE_TARGET, rule_bytes, 0o600)
            atomic_write(VALIDATOR_TARGET, validator_bytes, 0o750)
            atomic_write(VALIDATOR_LAUNCHER_TARGET, launcher_bytes, 0o750)
            installed_payloads(rule_bytes, validator_bytes, launcher_bytes)
            run_checked([str(COMMANDS["systemctl"]), "enable", "auditd.service"])
            if not service_state()["active"]:
                run_checked([str(COMMANDS["systemctl"]), "start", "auditd.service"])
            run_checked([str(COMMANDS["augenrules"]), "--load"])
            live = validate_live(rule_bytes, validator_bytes, launcher_bytes)
            record = {
                "schema": "codestra.host-auditd.installation.v1",
                "source_sha": args.source_sha,
                "change_id": args.change_id,
                "approver": args.approver,
                "installed_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
                "rollback_stamp": stamp,
                "rule_sha256": live["managed_rule_sha256"],
                "validator_sha256": live["validator_sha256"],
                "validator_launcher_sha256": live[
                    "validator_launcher_sha256"
                ],
                "release": release_binding,
                "state": live,
            }
            return persist_installation_record(record)
        except BaseException:
            restore_checkpoint(checkpoint, args.source_sha, stamp)
            raise
    finally:
        shutil.rmtree(stage)


def rollback(args: argparse.Namespace) -> dict[str, object]:
    require_prerequisites()
    if not SHA_RE.fullmatch(args.expected_source_sha) or not STAMP_RE.fullmatch(args.backup_stamp):
        raise InstallError("rollback identity rejected")
    checkpoint = BACKUP_ROOT / args.backup_stamp
    completed = completed_rollback_result(
        checkpoint, args.expected_source_sha, args.backup_stamp
    )
    if completed is not None:
        return completed
    restored = restore_checkpoint(
        checkpoint, args.expected_source_sha, args.backup_stamp
    )
    result = {
        "schema": "codestra.host-auditd.rollback-result.v1",
        "source_sha": args.expected_source_sha,
        "rollback_stamp": args.backup_stamp,
        "completed_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
        "restored": restored,
        "mutation_scope": list(ROLLBACK_MUTATION_SCOPE),
    }
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    atomic_write(checkpoint / ROLLBACK_RESULT_NAME, payload, 0o600)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="action", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("--source-sha", required=True)
    install_parser.add_argument("--change-id", required=True)
    install_parser.add_argument("--approver", required=True)
    install_parser.add_argument("--release-archive", required=True)
    install_parser.add_argument("--release-manifest", required=True)
    install_parser.add_argument("--release-checksums", required=True)
    install_parser.add_argument("--release-signature", required=True)
    rollback_parser = commands.add_parser("rollback")
    rollback_parser.add_argument("--backup-stamp", required=True)
    rollback_parser.add_argument("--expected-source-sha", required=True)
    return result


def main(argv: list[str]) -> int:
    try:
        args = parser().parse_args(argv)
        result = install(args) if args.action == "install" else rollback(args)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (InstallError, KeyError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"HOST_AUDITD=FAIL error={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
