#!/usr/bin/python3
"""Checksum- and signature-gated installer for the bounded operator."""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import ipaddress
import json
import os
import pwd
import re
import secrets
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
    "kpv_probe_core.py",
    "probe-authorization-tests",
    "probe-no-effect-tests",
    "probe-callback-tests",
    "probe-smtp-no-data",
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
EXPECTED_SOURCE_SCAN_FILES = [
    "build-operator-artifact.py",
    "klyrow-production-validator",
    "klyrow-production-validator-root",
    "klyrow-production-validator-actions",
    "klyrow_validator_core.py",
    "kpv_probe_core.py",
    "probe-authorization-tests",
    "probe-no-effect-tests",
    "probe-callback-tests",
    "probe-smtp-no-data",
    "install-klyrow-production-validator.py",
    "install_klyrow_production_validator_compat.py",
    "remove-klyrow-production-validator.py",
    "revoke-klyrow-validator-key.py",
    "validate-klyrow-production-validator.py",
]
STAGED_INPUTS = {
    "sha256s": ("SHA256SUMS", False, 65536),
    "signature": ("SHA256SUMS.sig", False, 65536),
    "allowed_signers": ("allowed_signers", True, 65536),
    "installation_manifest": ("installation-manifest.json", False, 2 * 1024 * 1024),
    "sbom": ("sbom.spdx.json", False, 2 * 1024 * 1024),
    "provenance": ("provenance.json", False, 2 * 1024 * 1024),
    "vulnerability_report": ("vulnerability-report.json", False, 2 * 1024 * 1024),
    "public_key": ("operator-key.pub", False, 65536),
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


def snapshot_file(
    source: Path, destination: Path, *, private: bool, maximum_bytes: int
) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise InstallError(f"unsafe file: {source}")
        if before.st_mode & (0o077 if private else 0o022):
            raise InstallError(f"unsafe mode: {source}")
        chunks = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(131072, maximum_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                raise InstallError(f"release input too large: {source.name}")
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise InstallError(f"release input changed during snapshot: {source.name}")
        current = source.lstat()
        if any(getattr(current, field) != getattr(after, field) for field in stable_fields):
            raise InstallError(f"release input path changed during snapshot: {source.name}")
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    output = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        written = 0
        while written < len(data):
            count = os.write(output, data[written:])
            if count <= 0:
                raise InstallError("release snapshot write failed")
            written += count
        os.fsync(output)
    finally:
        os.close(output)
    return data, after


def stage_install_inputs(args: argparse.Namespace, destination: Path) -> argparse.Namespace:
    metadata = destination.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise InstallError("unsafe release staging directory")
    if ARTIFACT_RE.fullmatch(args.archive.name) is None:
        raise InstallError("artifact name invalid")
    staged = argparse.Namespace(**vars(args))
    archive = destination / args.archive.name
    snapshot_file(args.archive, archive, private=False, maximum_bytes=32 * 1024 * 1024)
    staged.archive = archive
    for attribute, (name, private, maximum_bytes) in STAGED_INPUTS.items():
        target = destination / name
        snapshot_file(
            getattr(args, attribute),
            target,
            private=private,
            maximum_bytes=maximum_bytes,
        )
        setattr(staged, attribute, target)
    return staged


def mapped(root: Path | None, absolute: str) -> Path:
    path = Path(absolute)
    if not path.is_absolute():
        raise InstallError("installation target must be absolute")
    return path if root is None else root / path.relative_to("/")


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


def prepare_directory(path: Path, *, mode: int, uid: int, gid: int) -> None:
    validate_directory_chain(path.parent)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=mode, parents=True, exist_ok=False)
        os.chown(path, uid, gid)
        os.chmod(path, mode)
        metadata = path.lstat()
    validate_directory_chain(path)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != uid
        or metadata.st_mode & 0o022
    ):
        raise InstallError(f"unsafe installation directory: {path}")


def json_object(path: Path, *, maximum_bytes: int = 2 * 1024 * 1024) -> dict[str, object]:
    regular(path)
    if path.stat().st_size > maximum_bytes:
        raise InstallError(f"release evidence too large: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(f"invalid release evidence: {path.name}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"invalid release evidence: {path.name}")
    return value


def validate_release_evidence(
    *,
    source_sha: str,
    archive: Path,
    release_manifest_path: Path,
    sbom_path: Path,
    provenance_path: Path,
    vulnerability_path: Path,
) -> dict[str, object]:
    artifact_sha = sha256(archive)
    release_manifest = json_object(release_manifest_path)
    if (
        release_manifest.get("schema_version") != "1.0.0"
        or release_manifest.get("source_repository")
        != "appolon1908-hue/codestra-production-platform"
        or release_manifest.get("source_sha") != source_sha
        or release_manifest.get("artifact") != archive.name
        or release_manifest.get("artifact_sha256") != artifact_sha
        or release_manifest.get("application_runtime_mutations") != 0
    ):
        raise InstallError("release manifest authority mismatch")
    payload_hashes = release_manifest.get("payload_sha256")
    if (
        not isinstance(payload_hashes, dict)
        or set(payload_hashes) != EXPECTED_MEMBERS
        or not all(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            for value in payload_hashes.values()
        )
    ):
        raise InstallError("release payload manifest rejected")

    sbom = json_object(sbom_path)
    packages = sbom.get("packages")
    files = sbom.get("files")
    if (
        sbom.get("spdxVersion") != "SPDX-2.3"
        or sbom.get("name") != f"klyrow-production-validator-{source_sha}"
        or not isinstance(packages, list)
        or len(packages) != 1
        or not isinstance(packages[0], dict)
        or packages[0].get("versionInfo") != source_sha
        or {item.get("checksumValue") for item in packages[0].get("checksums", []) if isinstance(item, dict)}
        != {artifact_sha}
        or not isinstance(files, list)
    ):
        raise InstallError("SBOM authority mismatch")
    sbom_files: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("fileName"), str):
            raise InstallError("SBOM file entry rejected")
        checksums = item.get("checksums")
        if not isinstance(checksums, list) or len(checksums) != 1 or not isinstance(checksums[0], dict):
            raise InstallError("SBOM checksum entry rejected")
        if checksums[0].get("algorithm") != "SHA256" or not isinstance(
            checksums[0].get("checksumValue"), str
        ):
            raise InstallError("SBOM checksum entry rejected")
        sbom_files[item["fileName"]] = checksums[0]["checksumValue"]
    if sbom_files != payload_hashes:
        raise InstallError("SBOM payload binding mismatch")

    provenance = json_object(provenance_path)
    try:
        predicate = provenance["predicate"]
        build = predicate["buildDefinition"]
        run_details = predicate["runDetails"]
    except (KeyError, TypeError) as exc:
        raise InstallError("provenance schema rejected") from exc
    expected_subject = [{"name": archive.name, "digest": {"sha256": artifact_sha}}]
    expected_dependency = {
        "uri": "git+https://github.com/appolon1908-hue/codestra-production-platform",
        "digest": {"gitCommit": source_sha},
    }
    if (
        provenance.get("_type") != "https://in-toto.io/Statement/v1"
        or provenance.get("predicateType") != "https://slsa.dev/provenance/v1"
        or provenance.get("subject") != expected_subject
        or not isinstance(build, dict)
        or build.get("buildType")
        != "https://codestra.co/build/klyrow-production-validator/v1"
        or build.get("externalParameters") != {"source_sha": source_sha}
        or build.get("resolvedDependencies") != [expected_dependency]
        or not isinstance(run_details, dict)
        or run_details.get("builder")
        != {"id": ".github/workflows/klyrow-production-validator.yml"}
        or not isinstance(run_details.get("metadata"), dict)
        or not isinstance(run_details["metadata"].get("invocationId"), str)
        or not run_details["metadata"]["invocationId"]
    ):
        raise InstallError("provenance authority mismatch")

    vulnerability = json_object(vulnerability_path)
    source_scan = vulnerability.get("source_scan")
    findings = source_scan.get("findings") if isinstance(source_scan, dict) else None
    if (
        vulnerability.get("schema_version") != "2.0.0"
        or vulnerability.get("source_sha") != source_sha
        or vulnerability.get("dependency_lock") != "requirements.lock"
        or vulnerability.get("dependency_lock_sha256") != payload_hashes["requirements.lock"]
        or vulnerability.get("runtime_dependencies") != 0
        or not isinstance(source_scan, dict)
        or set(source_scan) != {
            "scanner",
            "scanner_version",
            "files_scanned",
            "errors",
            "findings",
        }
        or source_scan.get("scanner") != "bandit"
        or source_scan.get("scanner_version") != "1.9.4"
        or source_scan.get("files_scanned") != EXPECTED_SOURCE_SCAN_FILES
        or source_scan.get("errors") != 0
        or not isinstance(findings, dict)
        or set(findings) != {"high", "medium", "low"}
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in findings.values()
        )
        or vulnerability.get("critical") != "NOT_APPLICABLE_BANDIT_SEVERITY_MODEL"
        or vulnerability.get("high") != 0
        or findings.get("high") != vulnerability.get("high")
        or vulnerability.get("gate") != "PASS"
    ):
        raise InstallError("vulnerability gate rejected")
    return release_manifest


def verify_release(
    archive: Path,
    sums: Path,
    signature: Path,
    signers: Path,
    release_manifest_path: Path,
    sbom_path: Path,
    provenance_path: Path,
    vulnerability_path: Path,
) -> tuple[str, dict[str, object]]:
    evidence_paths = (
        archive,
        release_manifest_path,
        sbom_path,
        provenance_path,
        vulnerability_path,
    )
    for path in (*evidence_paths, sums, signature, signers):
        regular(path, private=path == signers)
    if sums.stat().st_size > 65536 or signature.stat().st_size > 65536 or signers.stat().st_size > 65536:
        raise InstallError("release signature authority too large")
    expected_names = {
        archive.name,
        "installation-manifest.json",
        "sbom.spdx.json",
        "provenance.json",
        "vulnerability-report.json",
    }
    if (
        release_manifest_path.name != "installation-manifest.json"
        or sbom_path.name != "sbom.spdx.json"
        or provenance_path.name != "provenance.json"
        or vulnerability_path.name != "vulnerability-report.json"
        or sums.name != "SHA256SUMS"
        or signature.name != "SHA256SUMS.sig"
    ):
        raise InstallError("release evidence filenames rejected")
    lines = sums.read_text(encoding="utf-8").splitlines()
    parsed: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if match is None or match.group(2) in parsed:
            raise InstallError("invalid checksum manifest")
        parsed[match.group(2)] = match.group(1)
    if set(parsed) != expected_names:
        raise InstallError("checksum manifest members rejected")
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
    for path in evidence_paths:
        if parsed.get(path.name) != sha256(path):
            raise InstallError(f"release checksum mismatch: {path.name}")
    match = ARTIFACT_RE.fullmatch(archive.name)
    if match is None:
        raise InstallError("artifact name invalid")
    source_sha = match.group(1)
    release_manifest = validate_release_evidence(
        source_sha=source_sha,
        archive=archive,
        release_manifest_path=release_manifest_path,
        sbom_path=sbom_path,
        provenance_path=provenance_path,
        vulnerability_path=vulnerability_path,
    )
    return source_sha, release_manifest


def safe_extract(archive: Path, destination: Path, source_sha: str) -> Path:
    prefix = f"klyrow-production-validator-{source_sha}"
    seen: set[str] = set()
    total_size = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 2:
                raise InstallError("unsafe archive path")
            if pure.parts[0] != prefix or pure.parts[1] not in EXPECTED_MEMBERS:
                raise InstallError("unexpected archive member")
            if not member.isfile() or member.issym() or member.islnk() or member.isdev():
                raise InstallError("unsafe archive member type")
            if member.size > 2 * 1024 * 1024:
                raise InstallError("archive member too large")
            total_size += member.size
            if total_size > 16 * 1024 * 1024:
                raise InstallError("archive payload too large")
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


def backup_file(
    target: Path, backup_dir: Path, label: str
) -> tuple[dict[str, object], bytes | None, os.stat_result | None]:
    validate_directory_chain(target.parent)
    record: dict[str, object] = {"target": str(target), "label": label, "present": False}
    destination = backup_dir / label
    try:
        data, metadata = snapshot_file(
            target,
            destination,
            private=label == "authorized_keys",
            maximum_bytes=8 * 1024 * 1024,
        )
    except FileNotFoundError:
        if target.exists() or target.is_symlink():
            raise InstallError(f"target appeared during backup: {target}")
        return record, None, None
    record.update(
        {
            "present": True,
            "sha256": hashlib.sha256(data).hexdigest(),
            "uid": metadata.st_uid,
            "gid": metadata.st_gid,
            "mode": metadata.st_mode & 0o777,
        }
    )
    return record, data, metadata


def rename_exchange(directory: int, left: str, right: str) -> None:
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise InstallError("atomic exchange unavailable") from exc
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        directory,
        os.fsencode(left),
        directory,
        os.fsencode(right),
        2,  # RENAME_EXCHANGE
    )
    if result != 0:
        error = ctypes.get_errno()
        if error in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
            raise InstallError("atomic exchange unsupported")
        raise OSError(error, os.strerror(error))


def atomic_replace_bytes(
    target: Path,
    content: bytes,
    expected_target: os.stat_result,
    *,
    expected_sha256: str,
    mode: int,
    uid: int,
    gid: int,
    label: str,
) -> os.stat_result:
    if not re.fullmatch(r"[a-z0-9-]{3,32}", label):
        raise InstallError("temporary label rejected")
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise InstallError("expected target digest rejected")
    validate_directory_chain(target.parent)
    directory = os.open(
        target.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    descriptor: int | None = None
    temporary: str | None = None
    exchanged = False
    preserve_temporary = False
    try:
        parent = os.fstat(directory)
        current_parent = target.parent.lstat()
        if current_parent.st_dev != parent.st_dev or current_parent.st_ino != parent.st_ino:
            raise InstallError("target directory changed before replace")
        for _attempt in range(32):
            candidate = f".{target.name}.kpv-{label}.{secrets.token_hex(12)}"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    mode,
                    dir_fd=directory,
                )
                temporary = candidate
                break
            except FileExistsError:
                continue
        if descriptor is None or temporary is None:
            raise InstallError("secure temporary file unavailable")
        written = 0
        while written < len(content):
            count = os.write(descriptor, content[written:])
            if count <= 0:
                raise InstallError("temporary file write failed")
            written += count
        os.fchmod(descriptor, mode)
        os.fchown(descriptor, uid, gid)
        os.fsync(descriptor)
        created = os.fstat(descriptor)
        temporary_metadata = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(temporary_metadata.st_mode)
            or temporary_metadata.st_dev != created.st_dev
            or temporary_metadata.st_ino != created.st_ino
        ):
            raise InstallError("secure temporary file replaced")
        current = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
        stable_target = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(
            getattr(current, field) != getattr(expected_target, field)
            for field in stable_target
        ):
            raise InstallError("target changed before replace")
        rename_exchange(directory, temporary, target.name)
        exchanged = True
        displaced = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
        installed = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
        displaced_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        displacement_matches = all(
            getattr(displaced, field) == getattr(expected_target, field)
            for field in displaced_fields
        )
        displaced_descriptor = os.open(
            temporary,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory,
        )
        try:
            displaced_before = os.fstat(displaced_descriptor)
            displaced_digest = hashlib.sha256()
            displaced_size = 0
            while True:
                chunk = os.read(displaced_descriptor, 65536)
                if not chunk:
                    break
                displaced_size += len(chunk)
                if displaced_size > 8 * 1024 * 1024:
                    raise InstallError("displaced target too large")
                displaced_digest.update(chunk)
            displaced_after = os.fstat(displaced_descriptor)
        finally:
            os.close(displaced_descriptor)
        displacement_matches = displacement_matches and all(
            getattr(displaced_before, field) == getattr(displaced_after, field)
            for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        )
        displacement_matches = (
            displacement_matches
            and displaced_before.st_dev == displaced.st_dev
            and displaced_before.st_ino == displaced.st_ino
            and displaced_digest.hexdigest() == expected_sha256
        )
        replacement_matches = (
            stat.S_ISREG(installed.st_mode)
            and installed.st_dev == created.st_dev
            and installed.st_ino == created.st_ino
        )
        canonical = target.lstat()
        canonical_matches = (
            canonical.st_dev == installed.st_dev and canonical.st_ino == installed.st_ino
        )
        if not displacement_matches or not replacement_matches or not canonical_matches:
            rename_exchange(directory, temporary, target.name)
            exchanged = False
            restored_temporary = os.stat(
                temporary, dir_fd=directory, follow_symlinks=False
            )
            if (
                restored_temporary.st_dev != created.st_dev
                or restored_temporary.st_ino != created.st_ino
            ):
                preserve_temporary = True
            raise InstallError("atomic target comparison failed")
        os.fsync(directory)
        final_displaced = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
        if (
            final_displaced.st_dev != displaced.st_dev
            or final_displaced.st_ino != displaced.st_ino
        ):
            preserve_temporary = True
            raise InstallError("displaced target changed before cleanup")
        os.unlink(temporary, dir_fd=directory)
        temporary = None
        exchanged = False
        return installed
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if exchanged and temporary is not None:
            try:
                rename_exchange(directory, temporary, target.name)
                exchanged = False
                restored_temporary = os.stat(
                    temporary, dir_fd=directory, follow_symlinks=False
                )
                if (
                    restored_temporary.st_dev != created.st_dev
                    or restored_temporary.st_ino != created.st_ino
                ):
                    preserve_temporary = True
            except (InstallError, OSError):
                preserve_temporary = True
        if temporary is not None and not preserve_temporary:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)


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
    prepare_directory(
        target.parent,
        mode=0o755 if uid == 0 else 0o700,
        uid=uid,
        gid=gid,
    )
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


def existing_installation_matches(
    *,
    simulator: Path | None,
    version_root: Path,
    source_sha: str,
    archive: Path,
    release_manifest_path: Path,
    sbom_path: Path,
    provenance_path: Path,
    vulnerability_path: Path,
    sums_path: Path,
    signature_path: Path,
    signers_path: Path,
    fingerprint: str,
    source_cidr: str,
    expiry: str,
    approver: str,
    change_id: str,
) -> bool:
    if version_root.is_symlink() or not version_root.is_dir():
        return False
    installation_path = mapped(
        simulator, "/etc/codestra/klyrow-production-validator/installation.json"
    )
    try:
        regular(installation_path, private=True)
        installation = json.loads(installation_path.read_text(encoding="utf-8"))
    except (InstallError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    expected = {
        "source_sha": source_sha,
        "artifact_sha256": sha256(archive),
        "release_manifest_sha256": sha256(release_manifest_path),
        "sbom_sha256": sha256(sbom_path),
        "provenance_sha256": sha256(provenance_path),
        "vulnerability_report_sha256": sha256(vulnerability_path),
        "checksum_manifest_sha256": sha256(sums_path),
        "signature_sha256": sha256(signature_path),
        "allowed_signers_sha256": sha256(signers_path),
        "release_signature_verification": "PASS",
        "change_id": change_id,
        "approver": approver,
        "key_fingerprint": fingerprint,
        "source_restriction": source_cidr,
        "expires_at": expiry,
        "application_runtime_changed": False,
    }
    if not isinstance(installation, dict) or any(
        installation.get(key) != value for key, value in expected.items()
    ):
        return False
    validator = version_root / "validate-klyrow-production-validator.py"
    try:
        regular(validator)
    except (InstallError, OSError):
        return False
    command = [
        "/usr/bin/python3",
        str(validator),
        "--expected-source-sha",
        source_sha,
    ]
    if simulator is not None:
        command.extend(["--simulator-root", str(simulator)])
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    return result.returncode == 0 and '"validation_result": "PASS"' in result.stdout


def unrestricted_public_key_line(line: str, key_type: str, key_blob: str) -> bool:
    fields = line.split()
    return len(fields) >= 2 and fields[0] == key_type and fields[1] == key_blob


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sha256s", required=True, type=Path)
    parser.add_argument("--signature", required=True, type=Path)
    parser.add_argument("--allowed-signers", required=True, type=Path)
    parser.add_argument("--installation-manifest", required=True, type=Path)
    parser.add_argument("--sbom", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--vulnerability-report", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--source-cidr", required=True)
    parser.add_argument("--expiry", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--change-id", required=True)
    parser.add_argument("--simulator-root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    simulator = args.simulator_root.resolve() if args.simulator_root else None
    if simulator is not None:
        marker = simulator / ".kpv-disposable-simulator"
        if not str(simulator).startswith("/tmp/kpv-simulator-") or not marker.is_file() or marker.is_symlink():
            raise SystemExit("INSTALL_RESULT=FAIL")
    elif os.geteuid() != 0:
        raise SystemExit("INSTALL_RESULT=FAIL")
    install_uid = os.geteuid() if simulator is not None else 0
    install_gid = os.getegid() if simulator is not None else 0
    backups: list[dict[str, object]] = []
    backup: Path | None = None
    version_root: Path | None = None
    staging_root: Path | None = None
    authorized_original: bytes | None = None
    authorized_original_metadata: os.stat_result | None = None
    authorized_installed_metadata: os.stat_result | None = None
    try:
        staging_root = Path(tempfile.mkdtemp(prefix="kpv-release-"))
        os.chmod(staging_root, 0o700)
        args = stage_install_inputs(args, staging_root)
        source_sha, release_manifest = verify_release(
            args.archive,
            args.sha256s,
            args.signature,
            args.allowed_signers,
            args.installation_manifest,
            args.sbom,
            args.provenance,
            args.vulnerability_report,
        )
        validate_authority(
            args.source_cidr,
            args.expiry,
            args.approver,
            args.change_id,
            simulator=simulator is not None,
        )
        public_key, fingerprint = public_key_details(args.public_key)
        codestra = pwd.getpwuid(os.geteuid()) if simulator is not None else pwd.getpwnam("codestra-admin")
        with tempfile.TemporaryDirectory(prefix="kpv-extract-") as temporary:
            payload = safe_extract(args.archive, Path(temporary), source_sha)
            payload_hashes = release_manifest["payload_sha256"]
            if not isinstance(payload_hashes, dict) or any(
                sha256(payload / name) != payload_hashes.get(name) for name in EXPECTED_MEMBERS
            ):
                raise InstallError("extracted payload digest mismatch")
            manifest = json.loads((payload / "command-contract.json").read_text(encoding="utf-8"))
            if manifest.get("allowed_user") != "codestra-admin" or manifest.get("default") != "deny":
                raise InstallError("command contract invalid")
            version_root = mapped(simulator, f"/opt/codestra/operators/klyrow-production-validator/{source_sha}")
            if version_root.exists() or version_root.is_symlink():
                if existing_installation_matches(
                    simulator=simulator,
                    version_root=version_root,
                    source_sha=source_sha,
                    archive=args.archive,
                    release_manifest_path=args.installation_manifest,
                    sbom_path=args.sbom,
                    provenance_path=args.provenance,
                    vulnerability_path=args.vulnerability_report,
                    sums_path=args.sha256s,
                    signature_path=args.signature,
                    signers_path=args.allowed_signers,
                    fingerprint=fingerprint,
                    source_cidr=args.source_cidr,
                    expiry=args.expiry,
                    approver=args.approver,
                    change_id=args.change_id,
                ):
                    print("INSTALL_RESULT=PASS")
                    print("INSTALL_IDEMPOTENT=YES")
                    print(f"SOURCE_SHA={source_sha}")
                    print(f"ARTIFACT_SHA256={sha256(args.archive)}")
                    print(f"KEY_FINGERPRINT={fingerprint}")
                    print("APPLICATION_RUNTIME_CHANGED=NO")
                    return 0
                raise InstallError("immutable version conflicts with requested installation")
            state = mapped(simulator, "/var/lib/codestra/klyrow-production-validator")
            prepare_directory(state, mode=0o700, uid=install_uid, gid=install_gid)
            backup_root = state / "install-backups"
            prepare_directory(backup_root, mode=0o700, uid=install_uid, gid=install_gid)
            backup = backup_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup.mkdir(mode=0o700, exist_ok=False)
            os.chown(backup, install_uid, install_gid)
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
                "probe-core": mapped(simulator, "/opt/codestra/operators/klyrow-production-validator/probes/kpv_probe_core.py"),
                "probe-authorization": mapped(simulator, "/opt/codestra/operators/klyrow-production-validator/probes/authorization-tests"),
                "probe-no-effect": mapped(simulator, "/opt/codestra/operators/klyrow-production-validator/probes/no-effect-tests"),
                "probe-callback": mapped(simulator, "/opt/codestra/operators/klyrow-production-validator/probes/callback-tests"),
                "probe-smtp": mapped(simulator, "/opt/codestra/operators/klyrow-production-validator/probes/smtp-no-data"),
                "probe-manifest": mapped(simulator, "/etc/codestra/klyrow-production-validator/probe-manifest.json"),
            }
            backup_results = {
                label: backup_file(path, backup, label)
                for label, path in targets.items()
            }
            backups = [result[0] for result in backup_results.values()]
            _, authorized_original, authorized_original_metadata = backup_results[
                "authorized_keys"
            ]
            if authorized_original is None or authorized_original_metadata is None:
                raise InstallError("existing authorized_keys authority is required")
            if (
                authorized_original_metadata.st_uid != codestra.pw_uid
                or authorized_original_metadata.st_gid != codestra.pw_gid
                or authorized_original_metadata.st_mode & 0o777 != 0o600
            ):
                raise InstallError("authorized_keys ownership or mode rejected")
            prepare_directory(
                version_root.parent, mode=0o755, uid=install_uid, gid=install_gid
            )
            version_root.mkdir(mode=0o755)
            os.chown(version_root, install_uid, install_gid)
            for name in EXPECTED_MEMBERS:
                atomic_install(payload / name, version_root / name, 0o755 if name.startswith(("klyrow-", "install-", "remove-", "validate-")) or name.endswith(".py") else 0o444, install_uid, install_gid)
            for source, name in (
                (args.installation_manifest, "release-installation-manifest.json"),
                (args.sbom, "release-sbom.spdx.json"),
                (args.provenance, "release-provenance.json"),
                (args.vulnerability_report, "release-vulnerability-report.json"),
                (args.sha256s, "release-SHA256SUMS"),
                (args.signature, "release-SHA256SUMS.sig"),
                (args.allowed_signers, "release-allowed-signers"),
            ):
                atomic_install(source, version_root / name, 0o444, install_uid, install_gid)
            atomic_install(payload / "klyrow-production-validator", targets["dispatcher"], 0o755, install_uid, install_gid)
            atomic_install(payload / "klyrow-production-validator-root", targets["root-helper"], 0o755, install_uid, install_gid)
            atomic_install(payload / "klyrow-production-validator-actions", targets["actions"], 0o755, install_uid, install_gid)
            atomic_install(payload / "klyrow_validator_core.py", targets["core"], 0o644, install_uid, install_gid)
            atomic_install(payload / "command-contract.json", targets["contract"], 0o444, install_uid, install_gid)
            atomic_install(payload / "klyrow-production-validator.sudoers", targets["sudoers"], 0o440, install_uid, install_gid)
            atomic_install(payload / "kpv_probe_core.py", targets["probe-core"], 0o444, install_uid, install_gid)
            for action, target_label in (
                ("authorization-tests", "probe-authorization"),
                ("no-effect-tests", "probe-no-effect"),
                ("callback-tests", "probe-callback"),
                ("smtp-no-data", "probe-smtp"),
            ):
                atomic_install(payload / f"probe-{action}", targets[target_label], 0o555, install_uid, install_gid)
            probe_manifest = {
                "schema_version": "1.0.0",
                "probe_core": {
                    "path": "/opt/codestra/operators/klyrow-production-validator/probes/kpv_probe_core.py",
                    "sha256": sha256(payload / "kpv_probe_core.py"),
                },
                "probes": {
                    action: {
                        "path": f"/opt/codestra/operators/klyrow-production-validator/probes/{action}",
                        "sha256": sha256(payload / f"probe-{action}"),
                    }
                    for action in (
                        "authorization-tests",
                        "no-effect-tests",
                        "callback-tests",
                        "smtp-no-data",
                    )
                },
            }
            probe_manifest_tmp = backup / "probe-manifest.new"
            probe_manifest_tmp.write_text(
                json.dumps(probe_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            atomic_install(
                probe_manifest_tmp, targets["probe-manifest"], 0o444, install_uid, install_gid
            )
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
            atomic_install(identity_tmp, targets["identity"], 0o444, install_uid, install_gid)
            authorized = targets["authorized_keys"]
            prepare_directory(
                authorized.parent, mode=0o700, uid=codestra.pw_uid, gid=codestra.pw_gid
            )
            try:
                existing = authorized_original.decode("utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise InstallError("authorized_keys encoding rejected") from exc
            key_type, key_blob = public_key.split()
            retained = [
                line
                for line in existing
                if not unrestricted_public_key_line(line, key_type, key_blob)
            ]
            forced = (
                f'from="{args.source_cidr}",expiry-time="{args.expiry}",'
                'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch",'
                "restrict,no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty,no-user-rc "
                + public_key
            )
            authorized_content = ("\n".join([*retained, forced]) + "\n").encode("utf-8")
            authorized_installed_metadata = atomic_replace_bytes(
                authorized,
                authorized_content,
                authorized_original_metadata,
                expected_sha256=hashlib.sha256(authorized_original).hexdigest(),
                mode=0o600,
                uid=codestra.pw_uid,
                gid=codestra.pw_gid,
                label="install",
            )
            installation = {
                "schema_version": "1.0.0",
                "source_sha": source_sha,
                "artifact_sha256": sha256(args.archive),
                "release_manifest_sha256": sha256(args.installation_manifest),
                "sbom_sha256": sha256(args.sbom),
                "provenance_sha256": sha256(args.provenance),
                "vulnerability_report_sha256": sha256(args.vulnerability_report),
                "checksum_manifest_sha256": sha256(args.sha256s),
                "signature_sha256": sha256(args.signature),
                "allowed_signers_sha256": sha256(args.allowed_signers),
                "release_signature_verification": "PASS",
                "installed_at_utc": datetime.now(timezone.utc).isoformat(),
                "change_id": args.change_id,
                "approver": args.approver,
                "key_fingerprint": fingerprint,
                "source_restriction": args.source_cidr,
                "expires_at": args.expiry,
                "authorized_keys_sha256": hashlib.sha256(authorized_content).hexdigest(),
                "backup_directory": str(backup),
                "backups": backups,
                "application_runtime_changed": False,
            }
            installation_tmp = backup / "installation.new"
            installation_tmp.write_text(json.dumps(installation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            atomic_install(installation_tmp, targets["installation"], 0o600, install_uid, install_gid)
        print("INSTALL_RESULT=PASS")
        print(f"SOURCE_SHA={source_sha}")
        print(f"ARTIFACT_SHA256={sha256(args.archive)}")
        print(f"KEY_FINGERPRINT={fingerprint}")
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 0
    except (InstallError, OSError, KeyError, ValueError, json.JSONDecodeError, tarfile.TarError):
        if backup is not None and backups:
            try:
                restore_backups(
                    [record for record in backups if record.get("label") != "authorized_keys"],
                    backup,
                )
                if (
                    authorized_installed_metadata is not None
                    and authorized_original is not None
                    and authorized_original_metadata is not None
                ):
                    atomic_replace_bytes(
                        Path(str(next(
                            record["target"]
                            for record in backups
                            if record.get("label") == "authorized_keys"
                        ))),
                        authorized_original,
                        authorized_installed_metadata,
                        expected_sha256=hashlib.sha256(authorized_content).hexdigest(),
                        mode=authorized_original_metadata.st_mode & 0o777,
                        uid=authorized_original_metadata.st_uid,
                        gid=authorized_original_metadata.st_gid,
                        label="rollback",
                    )
                if version_root is not None and version_root.is_dir() and not version_root.is_symlink():
                    shutil.rmtree(version_root)
            except (InstallError, OSError):
                print("INSTALL_ROLLBACK=FAIL")
        print("INSTALL_RESULT=FAIL")
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 2
    finally:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
