#!/usr/bin/python3
"""Checksum- and signature-gated installer for the bounded operator."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath


SOURCE_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")
ARTIFACT_RE = re.compile(r"\Aklyrow-production-validator-([0-9a-f]{40})\.tar\.gz\Z")
EXPIRY_RE = re.compile(r"\A20[0-9]{12}Z\Z")
CHANGE_RE = re.compile(r"\A[A-Z][A-Z0-9_-]{2,63}\Z")
EXPECTED_MEMBERS = {
    "klyrow-production-validator",
    "klyrow-production-validator-root",
    "klyrow-production-validator-actions",
    "klyrow_validator_core.py",
    "command-contract.json",
    "klyrow-production-validator.sudoers",
    "authorized_keys.template",
    "requirements.lock",
    "install-klyrow-production-validator.py",
    "install_klyrow_production_validator_compat.py",
    "remove-klyrow-production-validator.py",
    "revoke-klyrow-validator-key.py",
    "validate-klyrow-production-validator.py",
    "README.md",
}


class InstallError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def regular(path: Path, *, private: bool = False) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise InstallError(f"unsafe file: {path}")
    if metadata.st_mode & (0o077 if private else 0o022):
        raise InstallError(f"unsafe mode: {path}")


def mapped(root: Path | None, absolute: str) -> Path:
    path = Path(absolute)
    if not path.is_absolute():
        raise InstallError("installation target must be absolute")
    return path if root is None else root / path.relative_to("/")


def verify_release(archive: Path, sums: Path, signature: Path, signers: Path) -> str:
    for path in (archive, sums, signature, signers):
        regular(path, private=path == signers)
    lines = sums.read_text(encoding="utf-8").splitlines()
    parsed: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if match is None or match.group(2) in parsed:
            raise InstallError("invalid checksum manifest")
        parsed[match.group(2)] = match.group(1)
    if parsed.get(archive.name) != sha256(archive):
        raise InstallError("artifact checksum mismatch")
    verified = subprocess.run(
        [
            "/usr/bin/ssh-keygen",
            "-Y",
            "verify",
            "-q",
            "-f",
            str(signers),
            "-I",
            "codestra-release",
            "-n",
            "codestra-klyrow-validator",
            "-s",
            str(signature),
        ],
        input=sums.read_bytes(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if verified.returncode != 0:
        raise InstallError("release signature invalid")
    match = ARTIFACT_RE.fullmatch(archive.name)
    if match is None:
        raise InstallError("artifact name invalid")
    return match.group(1)


def safe_extract(archive: Path, destination: Path, source_sha: str) -> Path:
    prefix = f"klyrow-production-validator-{source_sha}"
    seen: set[str] = set()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 2:
                raise InstallError("unsafe archive path")
            if pure.parts[0] != prefix or pure.parts[1] not in EXPECTED_MEMBERS:
                raise InstallError("unexpected archive member")
            if not member.isfile() or member.issym() or member.islnk() or member.isdev():
                raise InstallError("unsafe archive member type")
            if pure.parts[1] in seen:
                raise InstallError("duplicate archive member")
            seen.add(pure.parts[1])
        if seen != EXPECTED_MEMBERS:
            raise InstallError("incomplete archive")
        bundle.extractall(destination, filter="data")
    return destination / prefix


def public_key_details(path: Path) -> tuple[str, str]:
    regular(path)
    lines = [line.strip() for line in path.read_text(encoding="ascii").splitlines() if line.strip()]
    if len(lines) != 1:
        raise InstallError("exactly one public key required")
    fields = lines[0].split()
    if len(fields) not in (2, 3) or fields[0] != "ssh-ed25519":
        raise InstallError("only a single Ed25519 key is accepted")
    result = subprocess.run(
        ["/usr/bin/ssh-keygen", "-lf", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise InstallError("invalid SSH public key")
    fingerprint = result.stdout.split()[1]
    return " ".join(fields[:2]), fingerprint


def validate_authority(
    source_cidr: str, expiry: str, approver: str, change_id: str, *, simulator: bool
) -> None:
    network = ipaddress.ip_network(source_cidr, strict=False)
    minimum_prefix = 24 if network.version == 4 else 64
    if network.prefixlen < minimum_prefix:
        raise InstallError("source restriction is too broad")
    if not EXPIRY_RE.fullmatch(expiry):
        raise InstallError("expiry must use OpenSSH YYYYMMDDHHMMSSZ format")
    expires = datetime.strptime(expiry, "%Y%m%d%H%M%SZ").replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise InstallError("authorization already expired")
    if not simulator and expires > datetime.now(timezone.utc) + timedelta(days=31):
        raise InstallError("authorization expiry exceeds 31 days")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{2,80}", approver):
        raise InstallError("approver invalid")
    if not CHANGE_RE.fullmatch(change_id):
        raise InstallError("change ID invalid")


def backup_file(target: Path, backup_dir: Path, label: str) -> dict[str, object]:
    record: dict[str, object] = {"target": str(target), "label": label, "present": False}
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():
            raise InstallError(f"unsafe existing target: {target}")
        destination = backup_dir / label
        shutil.copy2(target, destination, follow_symlinks=False)
        os.chmod(destination, 0o600)
        metadata = target.stat(follow_symlinks=False)
        record.update(
            {
                "present": True,
                "sha256": sha256(destination),
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "mode": metadata.st_mode & 0o777,
            }
        )
    return record


def restore_backups(records: list[dict[str, object]], backup_dir: Path) -> None:
    for record in reversed(records):
        target = Path(str(record["target"]))
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


def atomic_install(source: Path, target: Path, mode: int, uid: int, gid: int) -> None:
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise InstallError(f"unsafe install target: {target}")
    fd, temporary = tempfile.mkstemp(prefix=".kpv.", dir=target.parent)
    os.close(fd)
    temp_path = Path(temporary)
    try:
        shutil.copyfile(source, temp_path, follow_symlinks=False)
        os.chown(temp_path, uid, gid)
        os.chmod(temp_path, mode)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sha256s", required=True, type=Path)
    parser.add_argument("--signature", required=True, type=Path)
    parser.add_argument("--allowed-signers", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--source-cidr", required=True)
    parser.add_argument("--expiry", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--change-id", required=True)
    parser.add_argument("--simulator-root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if os.geteuid() != 0:
        raise SystemExit("INSTALL_RESULT=FAIL")
    simulator = args.simulator_root.resolve() if args.simulator_root else None
    if simulator is not None:
        marker = simulator / ".kpv-disposable-simulator"
        if not str(simulator).startswith("/tmp/kpv-simulator-") or not marker.is_file() or marker.is_symlink():
            raise SystemExit("INSTALL_RESULT=FAIL")
    backups: list[dict[str, object]] = []
    backup: Path | None = None
    version_root: Path | None = None
    try:
        source_sha = verify_release(args.archive, args.sha256s, args.signature, args.allowed_signers)
        validate_authority(
            args.source_cidr,
            args.expiry,
            args.approver,
            args.change_id,
            simulator=simulator is not None,
        )
        public_key, fingerprint = public_key_details(args.public_key)
        codestra = pwd.getpwnam("codestra-admin")
        with tempfile.TemporaryDirectory(prefix="kpv-extract-") as temporary:
            payload = safe_extract(args.archive, Path(temporary), source_sha)
            manifest = json.loads((payload / "command-contract.json").read_text(encoding="utf-8"))
            if manifest.get("allowed_user") != "codestra-admin" or manifest.get("default") != "deny":
                raise InstallError("command contract invalid")
            state = mapped(simulator, "/var/lib/codestra/klyrow-production-validator")
            backup = state / "install-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup.mkdir(mode=0o700, parents=True, exist_ok=False)
            targets = {
                "dispatcher": mapped(simulator, "/usr/local/libexec/codestra/klyrow-production-validator"),
                "root-helper": mapped(simulator, "/usr/local/libexec/codestra/klyrow-production-validator-root"),
                "actions": mapped(simulator, "/usr/local/libexec/codestra/klyrow-production-validator-actions"),
                "core": mapped(simulator, "/usr/local/libexec/codestra/klyrow_validator_core.py"),
                "contract": mapped(simulator, "/etc/codestra/klyrow-production-validator/command-contract.json"),
                "sudoers": mapped(simulator, "/etc/sudoers.d/klyrow-production-validator"),
                "identity": mapped(simulator, "/etc/codestra/klyrow-production-validator/operator-identity.json"),
                "authorized_keys": mapped(simulator, "/home/codestra-admin/.ssh/authorized_keys"),
                "installation": mapped(simulator, "/etc/codestra/klyrow-production-validator/installation.json"),
            }
            backups = [backup_file(path, backup, label) for label, path in targets.items()]
            version_root = mapped(simulator, f"/opt/codestra/operators/klyrow-production-validator/{source_sha}")
            if version_root.exists() or version_root.is_symlink():
                raise InstallError("immutable version already exists")
            version_root.mkdir(mode=0o755, parents=True)
            for name in EXPECTED_MEMBERS:
                atomic_install(payload / name, version_root / name, 0o755 if name.startswith(("klyrow-", "install-", "remove-", "validate-")) or name.endswith(".py") else 0o444, 0, 0)
            atomic_install(payload / "klyrow-production-validator", targets["dispatcher"], 0o755, 0, 0)
            atomic_install(payload / "klyrow-production-validator-root", targets["root-helper"], 0o755, 0, 0)
            atomic_install(payload / "klyrow-production-validator-actions", targets["actions"], 0o755, 0, 0)
            atomic_install(payload / "klyrow_validator_core.py", targets["core"], 0o644, 0, 0)
            atomic_install(payload / "command-contract.json", targets["contract"], 0o444, 0, 0)
            atomic_install(payload / "klyrow-production-validator.sudoers", targets["sudoers"], 0o440, 0, 0)
            if simulator is None:
                checked = subprocess.run(["/usr/sbin/visudo", "-cf", str(targets["sudoers"])], check=False)
                if checked.returncode != 0:
                    raise InstallError("sudoers validation failed")
            identity = {
                "key_fingerprint": fingerprint,
                "source_restriction": args.source_cidr,
                "expires_at": args.expiry,
                "owner": "codestra-admin",
                "approver": args.approver,
            }
            identity_tmp = backup / "identity.new"
            identity_tmp.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            atomic_install(identity_tmp, targets["identity"], 0o444, 0, 0)
            authorized = targets["authorized_keys"]
            authorized.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            existing = authorized.read_text(encoding="utf-8").splitlines() if authorized.exists() else []
            key_blob = public_key.split()[1]
            retained = [line for line in existing if key_blob not in line.split()]
            forced = (
                f'from="{args.source_cidr}",expiry-time="{args.expiry}",'
                'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch",'
                "restrict,no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty,no-user-rc "
                + public_key
            )
            authorized_tmp = backup / "authorized_keys.new"
            authorized_tmp.write_text("\n".join([*retained, forced]) + "\n", encoding="utf-8")
            atomic_install(authorized_tmp, authorized, 0o600, codestra.pw_uid, codestra.pw_gid)
            installation = {
                "schema_version": "1.0.0",
                "source_sha": source_sha,
                "artifact_sha256": sha256(args.archive),
                "installed_at_utc": datetime.now(timezone.utc).isoformat(),
                "change_id": args.change_id,
                "approver": args.approver,
                "key_fingerprint": fingerprint,
                "authorized_keys_sha256": sha256(authorized),
                "backup_directory": str(backup),
                "backups": backups,
                "application_runtime_changed": False,
            }
            installation_tmp = backup / "installation.new"
            installation_tmp.write_text(json.dumps(installation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            atomic_install(installation_tmp, targets["installation"], 0o600, 0, 0)
        print("INSTALL_RESULT=PASS")
        print(f"SOURCE_SHA={source_sha}")
        print(f"ARTIFACT_SHA256={sha256(args.archive)}")
        print(f"KEY_FINGERPRINT={fingerprint}")
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 0
    except (InstallError, OSError, KeyError, ValueError, json.JSONDecodeError, tarfile.TarError):
        if backup is not None and backups:
            try:
                restore_backups(backups, backup)
                if version_root is not None and version_root.is_dir() and not version_root.is_symlink():
                    shutil.rmtree(version_root)
            except (InstallError, OSError):
                print("INSTALL_ROLLBACK=FAIL")
        print("INSTALL_RESULT=FAIL")
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
