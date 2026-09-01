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
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
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
    "runuser": Path("/usr/sbin/runuser"),
    "service": Path("/usr/sbin/service"),
    "ssh-keygen": Path("/usr/bin/ssh-keygen"),
    "systemctl": Path("/usr/bin/systemctl"),
    "test": Path("/usr/bin/test"),
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
    INSTALLATION_RECORD: "installation.record",
}


class InstallError(RuntimeError):
    pass


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp_now() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
        "allowed_signers": (Path(args.allowed_signers), 64 * 1024, True),
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
    if fingerprint != args.expected_signer_fingerprint:
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
    for name, path in COMMANDS.items():
        if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
            raise InstallError(f"required audit command missing: {name}")
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
                filters.add(item)
        signatures.add(("syscall", action, tuple(sorted(syscalls)), tuple(sorted(filters)), key))
    return signatures


def validate_live(rule_bytes: bytes) -> dict[str, object]:
    status = audit_status()
    if status.get("enabled") not in {1, 2} or status.get("pid", 0) <= 0 or status.get("lost") != 0:
        raise InstallError("audit kernel state failed closed")
    state = service_state()
    if state != {"enabled": True, "active": True}:
        raise InstallError("auditd service is not enabled and active")
    installed = checked_regular(RULE_TARGET)
    if installed != rule_bytes:
        raise InstallError("installed managed rule differs from source")
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
        "managed_rule_sha256": sha256_bytes(installed),
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
    value = checked_regular(snapshot)
    if sha256_bytes(value) != record.get("sha256"):
        raise InstallError("rollback snapshot checksum mismatch")
    atomic_write(target, value, int(record["mode"]))
    os.chown(target, int(record["uid"]), int(record["gid"]), follow_symlinks=False)


def restore_checkpoint(checkpoint: Path, record: dict[str, object]) -> None:
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


def install(args: argparse.Namespace) -> dict[str, object]:
    require_prerequisites()
    if not SHA_RE.fullmatch(args.source_sha):
        raise InstallError("source SHA rejected")
    if not CHANGE_RE.fullmatch(args.change_id):
        raise InstallError("change ID rejected")
    if not APPROVER_RE.fullmatch(args.approver):
        raise InstallError("approver rejected")
    if FINGERPRINT_RE.fullmatch(args.expected_signer_fingerprint) is None:
        raise InstallError("expected signer fingerprint rejected")
    stage, staged, input_digests = snapshot_release_inputs(args)
    try:
        rule_bytes, validator_bytes, release_binding = verify_signed_release(
            args, stage, staged, input_digests
        )
        require_additive_rules(rule_bytes)
        status_before = audit_status()
        if RULE_TARGET.exists() and INSTALLATION_RECORD.exists() and VALIDATOR_TARGET.exists():
            existing_record = json.loads(checked_regular(INSTALLATION_RECORD))
            if (
                checked_regular(RULE_TARGET) == rule_bytes
                and checked_regular(VALIDATOR_TARGET) == validator_bytes
                and existing_record.get("source_sha") == args.source_sha
                and existing_record.get("change_id") == args.change_id
                and existing_record.get("approver") == args.approver
                and existing_record.get("release") == release_binding
            ):
                validate_live(rule_bytes)
                return existing_record
        if status_before["enabled"] == 2:
            raise InstallError("immutable kernel audit policy blocks this exact change")
        before = service_state()
        secure_directory(STATE_ROOT)
        stamp, checkpoint, rollback_record = snapshot_before(args.source_sha, before)
        try:
            atomic_write(RULE_TARGET, rule_bytes, 0o600)
            atomic_write(VALIDATOR_TARGET, validator_bytes, 0o750)
            run_checked([str(COMMANDS["systemctl"]), "enable", "auditd.service"])
            if not service_state()["active"]:
                run_checked([str(COMMANDS["systemctl"]), "start", "auditd.service"])
            run_checked([str(COMMANDS["augenrules"]), "--load"])
            live = validate_live(rule_bytes)
            record = {
                "schema": "codestra.host-auditd.installation.v1",
                "source_sha": args.source_sha,
                "change_id": args.change_id,
                "approver": args.approver,
                "installed_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
                "rollback_stamp": stamp,
                "rule_sha256": sha256_bytes(rule_bytes),
                "validator_sha256": sha256_bytes(validator_bytes),
                "release": release_binding,
                "state": live,
            }
            payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            atomic_write(INSTALLATION_RECORD, payload, 0o600)
            return record
        except BaseException:
            restore_checkpoint(checkpoint, rollback_record)
            raise
    finally:
        shutil.rmtree(stage)


def rollback(args: argparse.Namespace) -> dict[str, object]:
    require_prerequisites()
    if not SHA_RE.fullmatch(args.expected_source_sha) or not STAMP_RE.fullmatch(args.backup_stamp):
        raise InstallError("rollback identity rejected")
    checkpoint = BACKUP_ROOT / args.backup_stamp
    manifest = checked_regular(checkpoint / "rollback.json")
    checksums = checked_regular(checkpoint / "SHA256SUMS", max_bytes=4096).decode("ascii", "strict")
    if checksums != f"{sha256_bytes(manifest)}  rollback.json\n":
        raise InstallError("rollback manifest checksum mismatch")
    record = json.loads(manifest)
    if record.get("source_sha") != args.expected_source_sha or record.get("stamp") != args.backup_stamp:
        raise InstallError("rollback source identity mismatch")
    restore_checkpoint(checkpoint, record)
    result = {
        "schema": "codestra.host-auditd.rollback-result.v1",
        "source_sha": args.expected_source_sha,
        "rollback_stamp": args.backup_stamp,
        "completed_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
        "mutation_scope": [
            str(RULE_TARGET),
            str(AGGREGATE_TARGET),
            str(VALIDATOR_TARGET),
            str(INSTALLATION_RECORD),
            "auditd.service-state",
        ],
    }
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    atomic_write(checkpoint / "rollback-result.json", payload, 0o600)
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
    install_parser.add_argument("--allowed-signers", required=True)
    install_parser.add_argument("--expected-signer-fingerprint", required=True)
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
