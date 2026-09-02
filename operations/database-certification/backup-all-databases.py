#!/usr/bin/env python3
"""Create an encrypted, off-host, source-attributed Server A backup.

The script resolves Docker workloads through Compose labels. It never guesses
or depends on a generated container name. A production run is fail-closed
unless every required target, protected path, encryption input, off-host
destination, strict known-hosts file, and immutability evidence file is present
and unambiguous.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from runtime_contract import (
    ContractError,
    atomic_write,
    atomic_write_json,
    container_identity,
    find_mount,
    load_json,
    parse_remote,
    require_digest_image,
    require_executable,
    require_safe_id,
    resolve_compose_service,
    run_command,
    sha256_file,
    validate_protected_file,
    write_prometheus_textfile,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_TARGETS = ROOT / "database-targets.json"
DEFAULT_ALPINE_IMAGE = (
    "alpine@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
)
DEFAULT_PYTHON_IMAGE = (
    "python@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
)
ALLOWED_PROTECTED_ROOTS = (Path("/etc/codestra"), Path("/opt/codestra"))


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def require_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ContractError(f"required protected configuration is missing: {name}")
    if "\n" in value or "\r" in value:
        raise ContractError(f"configuration contains a newline: {name}")
    return value


def validate_gpg_fingerprint(value: str, *, field: str) -> str:
    fingerprint = value.upper()
    if not re.fullmatch(r"[0-9A-F]{40,64}", fingerprint):
        raise ContractError(f"{field} must be a 40-64 character hexadecimal fingerprint")
    return fingerprint


def require_gpg_key(gpg_home: Path, fingerprint: str, *, secret: bool) -> None:
    command = [
        "gpg",
        "--homedir",
        str(gpg_home),
        "--batch",
        "--lock-never",
        "--with-colons",
        "--fingerprint",
        "--list-secret-keys" if secret else "--list-keys",
        fingerprint,
    ]
    output = run_command(command).stdout.decode("utf-8", "replace")
    fingerprints = {
        parts[9].upper()
        for raw in output.splitlines()
        if (parts := raw.split(":")) and parts[0] == "fpr" and len(parts) > 9
    }
    if fingerprint not in fingerprints:
        kind = "secret signing" if secret else "recipient"
        raise ContractError(f"configured GPG {kind} fingerprint is unavailable")


def validate_immutability_evidence(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema") != "codestra.offhost-immutability-evidence.v1":
        raise ContractError("unsupported off-host immutability evidence schema")
    if payload.get("status") != "PASS":
        raise ContractError("off-host immutability evidence is not PASS")
    mode = payload.get("retention_mode")
    if mode not in {"OBJECT_LOCK", "WORM", "IMMUTABLE_SNAPSHOT"}:
        raise ContractError("off-host retention mode is not an approved immutable control")
    if payload.get("deletion_protection_tested") is not True:
        raise ContractError("off-host deletion protection has not been tested")
    provider_reference = str(payload.get("provider_reference", "")).strip()
    owner = str(payload.get("owner", "")).strip()
    if (
        not provider_reference
        or provider_reference.startswith("REPLACE_")
        or not owner
        or owner.startswith("REPLACE_")
    ):
        raise ContractError("off-host immutability evidence lacks provider/owner identity")
    try:
        verified_at = datetime.fromisoformat(str(payload["verified_at"]).replace("Z", "+00:00"))
        retention_until = datetime.fromisoformat(
            str(payload["retention_until"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise ContractError("off-host immutability evidence timestamps are invalid") from exc
    now = datetime.now(timezone.utc)
    if verified_at.tzinfo is None or retention_until.tzinfo is None:
        raise ContractError("off-host immutability timestamps must include a timezone")
    if verified_at > now or (now - verified_at).total_seconds() > 31 * 86400:
        raise ContractError("off-host immutability verification is future-dated or stale")
    if retention_until <= now:
        raise ContractError("off-host immutable retention has already expired")
    return {
        "status": "PASS",
        "retention_mode": mode,
        "provider_reference": provider_reference,
        "verified_at": verified_at.astimezone(timezone.utc).isoformat(),
        "retention_until": retention_until.astimezone(timezone.utc).isoformat(),
        "deletion_protection_tested": True,
        "owner": owner,
        "sha256": sha256_file(path),
    }


def docker_exec_bytes(
    container_id: str,
    *,
    os_user: str,
    command: list[str],
    timeout: int = 900,
) -> bytes:
    result = run_command(
        ["docker", "exec", "--user", os_user, container_id, *command],
        timeout=timeout,
    )
    return result.stdout


def psql_scalar(
    container_id: str,
    *,
    os_user: str,
    login_user: str,
    database: str,
    sql: str,
) -> str:
    output = docker_exec_bytes(
        container_id,
        os_user=os_user,
        command=[
            "psql",
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            login_user,
            "-d",
            database,
            "-c",
            sql,
        ],
    )
    return output.decode("utf-8", "replace").strip()


def verify_standby(
    container_id: str,
    *,
    os_user: str,
    login_user: str,
    database: str,
    maximum_lag: int,
) -> dict[str, Any]:
    state = psql_scalar(
        container_id,
        os_user=os_user,
        login_user=login_user,
        database=database,
        sql=(
            "select pg_is_in_recovery(),"
            "exists(select 1 from pg_stat_wal_receiver where status='streaming'),"
            "pg_last_wal_replay_lsn() is not null,"
            "coalesce(pg_wal_lsn_diff(pg_last_wal_receive_lsn(),"
            "pg_last_wal_replay_lsn())::bigint,0)"
        ),
    )
    parts = state.split("|")
    if len(parts) != 4:
        raise ContractError("standby state query returned an unexpected shape")
    recovery, receiving, replaying, lag_text = parts
    try:
        lag = int(lag_text)
    except ValueError as exc:
        raise ContractError("standby replay lag is not numeric") from exc
    if recovery != "t" or receiving != "t" or replaying != "t":
        raise ContractError("designated standby is not a streaming read-only replica")
    if lag < 0 or lag > maximum_lag:
        raise ContractError(
            f"standby replay lag {lag} exceeds maximum {maximum_lag} bytes"
        )
    return {
        "pg_is_in_recovery": True,
        "wal_receiver_streaming": True,
        "replay_lsn_present": True,
        "replay_lag_bytes": lag,
        "maximum_replay_lag_bytes": maximum_lag,
    }


def pause_services(contract: dict[str, Any]) -> list[str]:
    if os.environ.get("CODESTRA_BACKUP_QUIESCE_SERVICES", "YES") != "YES":
        raise ContractError(
            "CODESTRA_BACKUP_QUIESCE_SERVICES must remain YES for paired filestore backup"
        )
    paused: list[str] = []
    try:
        for item in contract.get("quiesce_services", []):
            inspected = resolve_compose_service(
                project=item["compose_project"], service=item["compose_service"]
            )
            container_id = inspected["Id"]
            run_command(["docker", "pause", container_id], timeout=60)
            paused.append(container_id)
        return paused
    except Exception:
        for container_id in reversed(paused):
            run_command(["docker", "unpause", container_id], check=False, timeout=60)
        raise


def resume_services(container_ids: Iterable[str]) -> None:
    failures: list[str] = []
    for container_id in reversed(list(container_ids)):
        result = run_command(
            ["docker", "unpause", container_id], check=False, timeout=60
        )
        if result.returncode != 0:
            failures.append(container_id[:12])
    if failures:
        raise ContractError(f"failed to resume quiesced containers: {','.join(failures)}")


def write_database_dumps(contract: dict[str, Any], work: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_database_ids: set[str] = set()
    for instance in contract.get("postgres_instances", []):
        inspected = resolve_compose_service(
            project=instance["compose_project"], service=instance["compose_service"]
        )
        identity = container_identity(inspected)
        container_id = inspected["Id"]
        os_user = instance.get("os_user", "postgres")
        backup_login_user = instance["backup_login_user"]
        databases = instance.get("databases") or []
        if not databases:
            raise ContractError(f"database instance has no databases: {instance['id']}")

        first_database = databases[0]["name"]
        standby: dict[str, Any] | None = None
        if instance.get("standby"):
            maximum_lag = int(instance.get("maximum_replay_lag_bytes", 0))
            if maximum_lag <= 0:
                raise ContractError("standby maximum replay lag must be positive")
            standby = verify_standby(
                container_id,
                os_user=os_user,
                login_user=backup_login_user,
                database=first_database,
                maximum_lag=maximum_lag,
            )

        roles_path = work / f"roles-{require_safe_id(instance['id'], field='instance id')}.sql"
        roles_path.write_bytes(
            docker_exec_bytes(
                container_id,
                os_user=os_user,
                command=["pg_dumpall", "-U", backup_login_user, "--roles-only"],
            )
        )
        os.chmod(roles_path, 0o600)

        for database in databases:
            database_id = require_safe_id(database["id"], field="database id")
            database_name = require_safe_id(database["name"], field="database name")
            if database_id in seen_database_ids:
                raise ContractError(f"duplicate database backup id: {database_id}")
            seen_database_ids.add(database_id)
            ready = docker_exec_bytes(
                container_id,
                os_user=os_user,
                command=["pg_isready", "-U", backup_login_user, "-d", database_name],
                timeout=60,
            ).decode("utf-8", "replace")
            if "accepting connections" not in ready:
                raise ContractError(f"database is not ready: {database_id}")
            dump_path = work / f"postgres-{database_id}.dump"
            dump_path.write_bytes(
                docker_exec_bytes(
                    container_id,
                    os_user=os_user,
                    command=[
                        "pg_dump",
                        "-U",
                        backup_login_user,
                        "-d",
                        database_name,
                        "-Fc",
                        "--no-owner",
                        "--no-acl",
                    ],
                    timeout=1800,
                )
            )
            os.chmod(dump_path, 0o600)
            if dump_path.stat().st_size == 0:
                raise ContractError(f"database dump is empty: {database_id}")
            catalog = psql_scalar(
                container_id,
                os_user=os_user,
                login_user=backup_login_user,
                database=database_name,
                sql=(
                    "select current_setting('server_version'),"
                    "pg_is_in_recovery(),"
                    "count(*) from information_schema.tables "
                    "where table_schema not in ('pg_catalog','information_schema')"
                ),
            )
            catalog_parts = catalog.split("|")
            if len(catalog_parts) != 3:
                raise ContractError(f"catalog query returned an unexpected shape: {database_id}")
            version, recovery, table_count_text = catalog_parts
            table_count = int(table_count_text)
            record = {
                "id": database_id,
                "source_database": database_name,
                "application": database.get("application"),
                "required": bool(database.get("required", True)),
                "archive_member": dump_path.name,
                "sha256": sha256_file(dump_path),
                "bytes": dump_path.stat().st_size,
                "server_version": version,
                "source_in_recovery": recovery == "t",
                "source_table_count": table_count,
                "runtime": identity,
                "backup_login_user": backup_login_user,
                "roles_archive_member": roles_path.name,
                "roles_sha256": sha256_file(roles_path),
            }
            if standby is not None:
                record["standby_validation"] = standby
            records.append(record)
    return records


def archive_sqlite_targets(
    contract: dict[str, Any], work: Path, python_image: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for target in contract.get("sqlite_targets", []):
        inspected = resolve_compose_service(
            project=target["compose_project"], service=target["compose_service"]
        )
        identity = container_identity(inspected)
        env_name = target["state_path_environment"]
        environment = inspected.get("Config", {}).get("Env") or []
        values = [entry.split("=", 1)[1] for entry in environment if entry.startswith(env_name + "=")]
        if len(values) != 1 or values[0] != target["expected_state_path"]:
            raise ContractError(f"SQLite state path mismatch: {target['id']}")
        find_mount(inspected, target["mount_destination"])
        target_id = require_safe_id(target["id"], field="sqlite target id")
        output_name = f"sqlite-{target_id}.sqlite3"
        code = """
import os, sqlite3
source_path=os.environ['SOURCE_DATABASE']
output_path=os.environ['OUTPUT_DATABASE']
source=sqlite3.connect(f'file:{source_path}?mode=ro', uri=True)
target=sqlite3.connect(output_path)
source.backup(target)
assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
assert target.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
target.close(); source.close()
"""
        run_command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--volumes-from",
                f"{inspected['Id']}:ro",
                "-v",
                f"{work}:/backup",
                "-e",
                f"SOURCE_DATABASE={target['expected_state_path']}",
                "-e",
                f"OUTPUT_DATABASE=/backup/{output_name}",
                python_image,
                "python",
                "-c",
                code,
            ],
            timeout=300,
        )
        output = work / output_name
        if not output.is_file() or output.stat().st_size == 0:
            raise ContractError(f"SQLite backup is empty: {target_id}")
        os.chmod(output, 0o600)
        records.append(
            {
                "id": target_id,
                "archive_member": output.name,
                "sha256": sha256_file(output),
                "bytes": output.stat().st_size,
                "runtime": identity,
            }
        )
    return records


def archive_volume_targets(
    contract: dict[str, Any], work: Path, alpine_image: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for target in contract.get("volume_archives", []):
        inspected = resolve_compose_service(
            project=target["compose_project"], service=target["compose_service"]
        )
        mount = find_mount(inspected, target["mount_destination"])
        target_id = require_safe_id(target["id"], field="volume target id")
        output_name = f"volume-{target_id}.tar.gz"
        run_command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--volumes-from",
                f"{inspected['Id']}:ro",
                "-v",
                f"{work}:/backup",
                alpine_image,
                "tar",
                "-czf",
                f"/backup/{output_name}",
                "-C",
                target["mount_destination"],
                ".",
            ],
            timeout=1800,
        )
        output = work / output_name
        if not output.is_file() or output.stat().st_size == 0:
            raise ContractError(f"volume archive is empty: {target_id}")
        os.chmod(output, 0o600)
        records.append(
            {
                "id": target_id,
                "archive_member": output.name,
                "sha256": sha256_file(output),
                "bytes": output.stat().st_size,
                "mount_type": mount.get("Type"),
                "mount_destination": mount.get("Destination"),
                "runtime": container_identity(inspected),
            }
        )
    return records


def allowed_protected_path(path: Path) -> bool:
    resolved = path.resolve()
    return any(root == resolved or root in resolved.parents for root in ALLOWED_PROTECTED_ROOTS)


def protected_tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if info.issym() or info.islnk() or info.isdev():
        raise ContractError(f"protected archive contains unsupported member: {info.name}")
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    return info


def archive_protected_paths(work: Path) -> dict[str, Any]:
    path_file = Path(require_environment("CODESTRA_PROTECTED_PATHS_FILE"))
    validate_protected_file(path_file, owner_uid=0)
    paths: list[Path] = []
    for raw in path_file.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        path = Path(value)
        if not path.is_absolute() or not allowed_protected_path(path):
            raise ContractError(f"protected path is outside approved roots: {path}")
        if path.is_symlink() or not path.exists():
            raise ContractError(f"protected path is missing or a symlink: {path}")
        paths.append(path)
    if not paths:
        raise ContractError("protected path list is empty")
    archive = work / "protected-configuration.tar.gz"
    with tarfile.open(archive, "w:gz", dereference=False) as tar:
        for path in paths:
            tar.add(path, arcname=str(path).lstrip("/"), filter=protected_tar_filter)
    os.chmod(archive, 0o600)
    return {
        "archive_member": archive.name,
        "sha256": sha256_file(archive),
        "bytes": archive.stat().st_size,
        "path_count": len(paths),
        "source_list_sha256": sha256_file(path_file),
    }


def make_plaintext_bundle(work: Path, manifest: dict[str, Any], destination: Path) -> None:
    manifest_path = work / "manifest.json"
    atomic_write_json(manifest_path, manifest)
    members: list[dict[str, Any]] = []
    for path in sorted(work.iterdir()):
        if path == destination or not path.is_file():
            continue
        members.append(
            {"name": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
        )
    checksum_manifest = work / "PLAINTEXT-SHA256.json"
    atomic_write_json(checksum_manifest, {"schema": "codestra.plaintext-checksums.v1", "files": members})
    with tarfile.open(destination, "w:gz", dereference=False) as tar:
        for path in sorted(work.iterdir()):
            if path == destination or not path.is_file():
                continue
            tar.add(path, arcname=path.name, recursive=False)
    os.chmod(destination, 0o600)


def ssh_options(identity: Path, known_hosts: Path) -> list[str]:
    return [
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-i", str(identity),
    ]


def upload_offhost(
    *, remote: str, stamp: str, files: list[Path], identity: Path, known_hosts: Path
) -> str:
    host, remote_root = parse_remote(remote)
    options = ssh_options(identity, known_hosts)
    remote_directory = f"{remote_root}/{stamp}"
    run_command(
        ["ssh", *options, host, f"install -d -m 0700 {shlex.quote(remote_directory)}"],
        timeout=60,
    )
    run_command(
        ["scp", "-q", *options, *[str(path) for path in files], f"{host}:{remote_directory}/"],
        timeout=1800,
    )
    encrypted = next(path for path in files if path.suffix == ".gpg")
    expected = sha256_file(encrypted)
    verification = run_command(
        [
            "ssh", *options, host,
            (
                f"cd {shlex.quote(remote_directory)} && "
                "sha256sum -c SHA256SUMS >/dev/null && "
                f"sha256sum {shlex.quote(encrypted.name)}"
            ),
        ],
        timeout=120,
    ).stdout.decode("utf-8", "replace").strip()
    actual = verification.split()[0] if verification else ""
    if actual != expected:
        raise ContractError("off-host checksum readback does not match local encrypted artifact")
    return actual


def synchronize_remote_status(
    *, remote: str, stamp: str, status_file: Path, identity: Path, known_hosts: Path
) -> str:
    """Upload the final PASS status only after the remote archive is verified."""
    host, remote_root = parse_remote(remote)
    options = ssh_options(identity, known_hosts)
    remote_directory = f"{remote_root}/{stamp}"
    run_command(
        ["scp", "-q", *options, str(status_file), f"{host}:{remote_directory}/STATUS.json"],
        timeout=120,
    )
    expected = sha256_file(status_file)
    readback = run_command(
        ["ssh", *options, host, f"sha256sum {shlex.quote(remote_directory + '/STATUS.json')}"],
        timeout=60,
    ).stdout.decode("utf-8", "replace").strip()
    actual = readback.split()[0] if readback else ""
    if actual != expected:
        raise ContractError("off-host status readback does not match local final status")
    return actual


def publish_metrics(path: Path, *, success: bool, stamp_epoch: int, duration: float) -> None:
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_database_backup_last_success_timestamp_seconds Unix timestamp of the last successful database backup.",
            "# TYPE codestra_database_backup_last_success_timestamp_seconds gauge",
            f"codestra_database_backup_last_success_timestamp_seconds {stamp_epoch if success else 0}",
            "# HELP codestra_database_backup_last_run_success Whether the latest backup run succeeded.",
            "# TYPE codestra_database_backup_last_run_success gauge",
            f"codestra_database_backup_last_run_success {1 if success else 0}",
            "# HELP codestra_database_backup_last_duration_seconds Duration of the latest backup run.",
            "# TYPE codestra_database_backup_last_duration_seconds gauge",
            f"codestra_database_backup_last_duration_seconds {duration:.3f}",
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--run", action="store_true")
    return parser.parse_args()


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema") != "codestra.database-backup-targets.v2":
        raise ContractError("unsupported database target contract schema")
    if contract.get("environment") != "production":
        raise ContractError("database target contract must explicitly identify production")
    ids: set[str] = set()
    for instance in contract.get("postgres_instances", []):
        require_safe_id(instance["id"], field="instance id")
        for database in instance.get("databases", []):
            database_id = require_safe_id(database["id"], field="database id")
            if database_id in ids:
                raise ContractError(f"duplicate database id: {database_id}")
            ids.add(database_id)
    if "keycloak" not in ids:
        raise ContractError("Keycloak database must be present in the target contract")


def preflight(contract: dict[str, Any]) -> dict[str, Any]:
    runtimes: list[dict[str, Any]] = []
    for instance in contract.get("postgres_instances", []):
        inspected = resolve_compose_service(
            project=instance["compose_project"], service=instance["compose_service"]
        )
        identity = container_identity(inspected)
        identity["target_id"] = instance["id"]
        runtimes.append(identity)
    for target in contract.get("sqlite_targets", []):
        inspected = resolve_compose_service(
            project=target["compose_project"], service=target["compose_service"]
        )
        find_mount(inspected, target["mount_destination"])
        identity = container_identity(inspected)
        identity["target_id"] = target["id"]
        runtimes.append(identity)
    for target in contract.get("volume_archives", []):
        inspected = resolve_compose_service(
            project=target["compose_project"], service=target["compose_service"]
        )
        find_mount(inspected, target["mount_destination"])
    return {
        "schema": "codestra.database-backup-preflight.v1",
        "status": "PASS",
        "environment": "production",
        "runtime_count": len(runtimes),
        "runtimes": runtimes,
    }


def main() -> int:
    args = parse_args()
    started_monotonic = time.monotonic()
    stamp = utc_stamp()
    metrics_path = Path(
        os.environ.get(
            "CODESTRA_DATABASE_BACKUP_METRICS_FILE",
            "/var/lib/node_exporter/textfile_collector/codestra_database_backup.prom",
        )
    )
    try:
        for executable in ("docker", "gpg", "ssh", "scp"):
            require_executable(executable)
        contract = load_json(args.targets)
        validate_contract(contract)
        preflight_result = preflight(contract)
        if args.preflight:
            print(json.dumps(preflight_result, sort_keys=True, indent=2))
            return 0

        backup_root = Path(
            os.environ.get(
                "CODESTRA_DATABASE_BACKUP_ROOT",
                "/opt/codestra/backups/database-certification",
            )
        )
        if not backup_root.is_absolute():
            raise ContractError("CODESTRA_DATABASE_BACKUP_ROOT must be absolute")
        backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(backup_root, 0o700)
        minimum_free = int(os.environ.get("CODESTRA_DATABASE_BACKUP_MINIMUM_FREE_PERCENT", "20"))
        if minimum_free < 5 or minimum_free > 50:
            raise ContractError("minimum free percentage must be between 5 and 50")
        disk = shutil.disk_usage(backup_root)
        free_percent = int((disk.free * 100) / disk.total)
        if free_percent < minimum_free:
            raise ContractError(
                f"backup filesystem free space {free_percent}% is below {minimum_free}%"
            )

        gpg_home = Path(require_environment("CODESTRA_DATABASE_BACKUP_GPG_HOME"))
        gpg_recipient = validate_gpg_fingerprint(
            require_environment("CODESTRA_DATABASE_BACKUP_GPG_RECIPIENT"),
            field="CODESTRA_DATABASE_BACKUP_GPG_RECIPIENT",
        )
        gpg_signing_key = validate_gpg_fingerprint(
            require_environment("CODESTRA_DATABASE_BACKUP_GPG_SIGNING_KEY"),
            field="CODESTRA_DATABASE_BACKUP_GPG_SIGNING_KEY",
        )
        remote = require_environment("CODESTRA_DATABASE_BACKUP_REMOTE")
        ssh_identity = Path(require_environment("CODESTRA_DATABASE_BACKUP_SSH_IDENTITY"))
        known_hosts = Path(require_environment("CODESTRA_DATABASE_BACKUP_KNOWN_HOSTS"))
        immutability_evidence = Path(
            require_environment("CODESTRA_BACKUP_IMMUTABILITY_EVIDENCE_FILE")
        )
        validate_protected_file(ssh_identity, owner_uid=0)
        validate_protected_file(known_hosts, owner_uid=0)
        validate_protected_file(immutability_evidence, owner_uid=0)
        immutability = validate_immutability_evidence(immutability_evidence)
        if not gpg_home.is_dir():
            raise ContractError("configured GPG home is unavailable")
        require_gpg_key(gpg_home, gpg_recipient, secret=False)
        require_gpg_key(gpg_home, gpg_signing_key, secret=True)
        alpine_image = require_digest_image(
            os.environ.get("CODESTRA_BACKUP_ALPINE_IMAGE", DEFAULT_ALPINE_IMAGE),
            field="CODESTRA_BACKUP_ALPINE_IMAGE",
        )
        python_image = require_digest_image(
            os.environ.get("CODESTRA_BACKUP_PYTHON_IMAGE", DEFAULT_PYTHON_IMAGE),
            field="CODESTRA_BACKUP_PYTHON_IMAGE",
        )

        final = backup_root / stamp
        final_partial = backup_root / f".{stamp}.partial"
        if final.exists() or final_partial.exists():
            raise ContractError("backup timestamp collision")
        final_partial.mkdir(mode=0o700)
        paused: list[str] = []
        try:
            with tempfile.TemporaryDirectory(prefix=f".plaintext-{stamp}-", dir=backup_root) as temporary:
                work = Path(temporary)
                os.chmod(work, 0o700)
                paused = pause_services(contract)
                try:
                    postgres_records = write_database_dumps(contract, work)
                    sqlite_records = archive_sqlite_targets(contract, work, python_image)
                    volume_records = archive_volume_targets(contract, work, alpine_image)
                    protected_record = archive_protected_paths(work)
                finally:
                    resume_services(paused)
                    paused = []

                manifest = {
                    "schema": "codestra.database-backup-manifest.v2",
                    "timestamp": stamp,
                    "timestamp_epoch": int(datetime.now(timezone.utc).timestamp()),
                    "environment": "production",
                    "source_authority": "appolon1908-hue/codestra-production-platform",
                    "target_contract_sha256": sha256_file(args.targets),
                    "preflight": preflight_result,
                    "postgres_databases": postgres_records,
                    "sqlite_databases": sqlite_records,
                    "volume_archives": volume_records,
                    "protected_configuration": protected_record,
                    "immutability_evidence": immutability,
                    "production_business_writes_executed": False,
                }
                plaintext_bundle = work / f"databases-{stamp}.tar.gz"
                make_plaintext_bundle(work, manifest, plaintext_bundle)
                encrypted = final_partial / f"databases-{stamp}.tar.gz.gpg"
                run_command(
                    [
                        "gpg",
                        "--homedir", str(gpg_home),
                        "--no-random-seed-file",
                        "--no-auto-check-trustdb",
                        "--lock-never",
                        "--batch",
                        "--yes",
                        "--trust-model", "always",
                        "--local-user", gpg_signing_key,
                        "--sign",
                        "--recipient", gpg_recipient,
                        "--encrypt",
                        "--output", str(encrypted),
                        str(plaintext_bundle),
                    ],
                    timeout=1800,
                )
                if not encrypted.is_file() or encrypted.stat().st_size == 0:
                    raise ContractError("encrypted backup artifact is empty")
                encrypted_digest = sha256_file(encrypted)
                atomic_write(
                    final_partial / "SHA256SUMS",
                    f"{encrypted_digest}  {encrypted.name}\n".encode(),
                    mode=0o600,
                )
                status = {
                    "schema": "codestra.database-backup-status.v2",
                    "status": "PASS",
                    "timestamp": stamp,
                    "database_dump_count": len(postgres_records),
                    "sqlite_backup_count": len(sqlite_records),
                    "volume_archive_count": len(volume_records),
                    "protected_configuration": "PASS",
                    "checksum": "PASS",
                    "encryption": "PASS",
                    "off_host_copy": "PENDING",
                    "immutable_retention": "PASS",
                    "immutable_retention_mode": immutability["retention_mode"],
                    "immutable_retention_until": immutability["retention_until"],
                    "gpg_signing_fingerprint": gpg_signing_key,
                    "encrypted_sha256": encrypted_digest,
                    "production_business_writes_executed": False,
                }
                atomic_write_json(final_partial / "STATUS.json", status)

            remote_digest = upload_offhost(
                remote=remote,
                stamp=stamp,
                files=[
                    final_partial / f"databases-{stamp}.tar.gz.gpg",
                    final_partial / "SHA256SUMS",
                ],
                identity=ssh_identity,
                known_hosts=known_hosts,
            )
            status["off_host_copy"] = "PASS"
            status["off_host_sha256"] = remote_digest
            status["duration_seconds"] = round(time.monotonic() - started_monotonic, 3)
            atomic_write_json(final_partial / "STATUS.json", status)
            remote_status_digest = synchronize_remote_status(
                remote=remote,
                stamp=stamp,
                status_file=final_partial / "STATUS.json",
                identity=ssh_identity,
                known_hosts=known_hosts,
            )
            atomic_write(
                final_partial / "REMOTE-STATUS-SHA256",
                f"{remote_status_digest}  STATUS.json\n".encode(),
                mode=0o600,
            )
            os.replace(final_partial, final)
            atomic_write(backup_root / "LAST_SUCCESS", f"{stamp}\n".encode(), mode=0o600)
            publish_metrics(
                metrics_path,
                success=True,
                stamp_epoch=int(
                    datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                ),
                duration=time.monotonic() - started_monotonic,
            )
            print(json.dumps(status, sort_keys=True))
            return 0
        finally:
            if paused:
                resume_services(paused)
            if final_partial.exists():
                shutil.rmtree(final_partial, ignore_errors=True)
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        try:
            publish_metrics(
                metrics_path,
                success=False,
                stamp_epoch=0,
                duration=time.monotonic() - started_monotonic,
            )
        except Exception:
            pass
        print("DATABASE_BACKUP=FAIL", file=sys.stderr)
        print(f"DATABASE_BACKUP_ERROR={str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
