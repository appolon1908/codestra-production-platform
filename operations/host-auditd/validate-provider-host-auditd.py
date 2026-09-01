#!/usr/bin/python3
"""Fail-closed host auditd certification with bounded durable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shlex
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path


RULE_TARGET = Path("/etc/audit/rules.d/60-codestra-provider-host.rules")
VALIDATOR_TARGET = Path("/usr/local/sbin/validate-codestra-provider-host-auditd")
VALIDATOR_LAUNCHER = Path(
    "/usr/local/sbin/validate-codestra-provider-host-auditd-verified"
)
INSTALLATION_RECORD = Path("/var/lib/codestra/host-auditd/installation.json")
EVIDENCE_ROOT = Path("/var/lib/codestra/host-auditd/evidence")
AUDIT_CONFIG = Path("/etc/audit/auditd.conf")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_KEYS = {
    "codestra_ssh_authority",
    "codestra_sudo_authority",
    "codestra_audit_authority",
    "codestra_release_trust",
    "codestra_operator_key",
    "codestra_operator_code",
    "codestra_operator_state",
    "codestra_root_session_exec",
    "codestra_privileged_exec",
    "codestra_service_privileged_exec",
    "codestra_unset_privileged_exec",
}


class ValidationError(RuntimeError):
    pass


def run(command: list[str], *, timeout: int = 60) -> str:
    result = subprocess.run(
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    return result.stdout


def checked_regular(path: Path, max_bytes: int = 1024 * 1024) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0:
            raise ValidationError(f"unsafe root-owned file: {path}")
        if stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > max_bytes:
            raise ValidationError(f"unsafe file mode or size: {path}")
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
            raise ValidationError(f"oversized file: {path}")
        return value
    finally:
        os.close(descriptor)


def checked_root_file_metadata(path: Path) -> os.stat_result:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            raise ValidationError(f"unsafe root-owned file: {path}")
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise ValidationError(f"unsafe file mode: {path}")
        return info
    finally:
        os.close(descriptor)


def write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise ValidationError("short evidence write rejected")
        view = view[written:]


def durable_evidence(path: Path, value: bytes) -> tuple[str, int]:
    parent = path.parent.parent
    parent_info = parent.lstat()
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or parent_info.st_uid != 0
        or parent_info.st_gid != 0
        or stat.S_IMODE(parent_info.st_mode) & 0o022
    ):
        raise ValidationError("unsafe evidence parent")
    if path.parent.exists():
        info = path.parent.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise ValidationError("unsafe evidence directory")
    else:
        path.parent.mkdir(mode=0o700)
        os.chown(path.parent, 0, 0)
    os.chmod(path.parent, 0o700)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        write_all(descriptor, value)
        os.fchmod(descriptor, 0o600)
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
    persisted = checked_regular(path)
    if persisted != value:
        raise ValidationError("evidence read-back mismatch")
    return hashlib.sha256(persisted).hexdigest(), len(persisted)


def audit_status(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in value.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in {"enabled", "pid", "lost", "backlog", "backlog_limit"}:
            try:
                result[fields[0]] = int(fields[1])
            except ValueError as exc:
                raise ValidationError("invalid audit kernel status") from exc
    if set(result) != {"enabled", "pid", "lost", "backlog", "backlog_limit"}:
        raise ValidationError("incomplete audit kernel status")
    return result


def rule_keys(value: str) -> set[str]:
    result: set[str] = set()
    for line in value.splitlines():
        match = re.search(r"(?:-k\s+|-F\s+key=)([A-Za-z0-9_.-]+)", line)
        if match:
            result.add(match.group(1))
    return result


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
            signatures.add(
                (
                    "watch",
                    tokens[tokens.index("-w") + 1],
                    "".join(sorted(tokens[tokens.index("-p") + 1])),
                    key,
                )
            )
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


def log_path() -> Path:
    config = checked_regular(AUDIT_CONFIG, max_bytes=256 * 1024).decode("utf-8", "strict")
    values = []
    for line in config.splitlines():
        candidate = line.partition("#")[0].strip()
        if candidate.startswith("log_file") and "=" in candidate:
            values.append(candidate.split("=", 1)[1].strip())
    if len(values) != 1:
        raise ValidationError("audit log path is ambiguous")
    path = Path(values[0])
    if not path.is_absolute() or path != Path("/var/log/audit/audit.log"):
        raise ValidationError("audit log path rejected")
    parent = path.parent.lstat()
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0:
        raise ValidationError("audit log directory rejected")
    checked_root_file_metadata(path)
    return path


def operator_cannot_modify(paths: list[Path]) -> bool:
    account = pwd.getpwnam("codestra-admin")
    for path in paths:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            return False
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid == account.pw_uid and mode & 0o200:
            return False
        if info.st_gid == account.pw_gid and mode & 0o020:
            return False
        if mode & 0o002:
            return False
        result = subprocess.run(
            ["/usr/sbin/runuser", "--user", account.pw_name, "--", "/usr/bin/test", "-w", str(path)],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
        if result.returncode == 0:
            return False
        if result.returncode != 1:
            raise ValidationError("operator writability check failed")
    return True


def installed_release_binding(
    expected_source_sha: str,
) -> tuple[bytes, str, str, str]:
    installed_rule = checked_regular(RULE_TARGET)
    installed_validator = checked_regular(
        VALIDATOR_TARGET, max_bytes=2 * 1024 * 1024
    )
    installed_launcher = checked_regular(
        VALIDATOR_LAUNCHER, max_bytes=2 * 1024 * 1024
    )
    installation = json.loads(checked_regular(INSTALLATION_RECORD))
    if not isinstance(installation, dict):
        raise ValidationError("installation record rejected")
    rule_sha = hashlib.sha256(installed_rule).hexdigest()
    validator_sha = hashlib.sha256(installed_validator).hexdigest()
    launcher_sha = hashlib.sha256(installed_launcher).hexdigest()
    if (
        installation.get("source_sha") != expected_source_sha
        or installation.get("rule_sha256") != rule_sha
    ):
        raise ValidationError("installation source binding mismatch")
    if installation.get("validator_sha256") != validator_sha:
        raise ValidationError("installation validator binding mismatch")
    if installation.get("validator_launcher_sha256") != launcher_sha:
        raise ValidationError("installation validator launcher binding mismatch")
    return installed_rule, rule_sha, validator_sha, launcher_sha


def validate(expected_source_sha: str) -> dict[str, object]:
    if os.geteuid() != 0:
        raise ValidationError("validator must run as root")
    if not SHA_RE.fullmatch(expected_source_sha):
        raise ValidationError("expected source SHA rejected")
    active = run(["/usr/bin/systemctl", "is-active", "auditd.service"]).strip()
    enabled = run(["/usr/bin/systemctl", "is-enabled", "auditd.service"]).strip()
    if active != "active" or enabled != "enabled":
        raise ValidationError("auditd service state rejected")
    status = audit_status(run(["/usr/sbin/auditctl", "-s"]))
    if status["enabled"] not in {1, 2} or status["pid"] <= 0 or status["lost"] != 0:
        raise ValidationError("audit kernel state rejected")
    if status["backlog"] >= status["backlog_limit"]:
        raise ValidationError("audit kernel backlog exhausted")
    installed, rule_sha, validator_sha, launcher_sha = installed_release_binding(
        expected_source_sha
    )
    active_rules = run(["/usr/sbin/auditctl", "-l"])
    active_keys = rule_keys(active_rules)
    if not REQUIRED_KEYS <= active_keys:
        raise ValidationError("managed audit keys are not all active")
    expected_signatures = managed_rule_signatures(installed.decode("utf-8", "strict"), REQUIRED_KEYS)
    active_signatures = managed_rule_signatures(active_rules, REQUIRED_KEYS)
    if expected_signatures != active_signatures:
        raise ValidationError("managed audit rule semantics differ from source")
    audit_log = log_path()
    if not operator_cannot_modify(
        [
            RULE_TARGET.parent,
            RULE_TARGET,
            VALIDATOR_TARGET.parent,
            VALIDATOR_TARGET,
            VALIDATOR_LAUNCHER.parent,
            VALIDATOR_LAUNCHER,
            INSTALLATION_RECORD.parent,
            INSTALLATION_RECORD,
            audit_log.parent,
            audit_log,
        ]
    ):
        raise ValidationError("codestra-admin can modify audit authority")
    correlation = uuid.uuid4().hex
    marker = f"CODESTRA_HOST_AUDIT_TEST_{correlation}"
    run(["/usr/sbin/auditctl", "-m", marker])
    found = False
    for _ in range(10):
        try:
            found = marker in run(["/usr/sbin/ausearch", "-m", "USER", "--start", "recent", "--raw"])
        except subprocess.CalledProcessError:
            found = False
        if found:
            break
        time.sleep(0.1)
    if not found:
        raise ValidationError("synthetic audit read-back failed")
    return {
        "schema": "codestra.host-auditd.validation.v1",
        "source_sha": expected_source_sha,
        "correlation_id": correlation,
        "service": "enabled-active",
        "kernel_enabled": status["enabled"],
        "lost_records": status["lost"],
        "backlog": status["backlog"],
        "backlog_limit": status["backlog_limit"],
        "rule_sha256": rule_sha,
        "validator_sha256": validator_sha,
        "validator_launcher_sha256": launcher_sha,
        "managed_keys": sorted(REQUIRED_KEYS),
        "audit_log": str(audit_log),
        "audit_log_root_owned": True,
        "operator_cannot_modify": True,
        "synthetic_readback": "PASS",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source-sha", required=True)
    args = parser.parse_args(argv)
    try:
        record = validate(args.expected_source_sha)
        payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        destination = EVIDENCE_ROOT / f"{record['correlation_id']}.json"
        digest, size = durable_evidence(destination, payload)
        report = {
            **record,
            "evidence_path": str(destination),
            "evidence_sha256": digest,
            "evidence_size": size,
            "result": "PASS",
        }
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValidationError, KeyError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"HOST_AUDITD_VALIDATION=FAIL error={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
