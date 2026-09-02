#!/usr/bin/env python3
"""Restore the encrypted off-host Server A backup into an isolated network."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_contract import (
    ContractError,
    atomic_write,
    atomic_write_json,
    load_json,
    parse_remote,
    require_digest_image,
    require_executable,
    require_safe_id,
    run_command,
    safe_extract_tar,
    sha256_file,
    validate_protected_file,
    write_prometheus_textfile,
)

DEFAULT_POSTGRES_IMAGE = (
    "postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94"
)
DEFAULT_PYTHON_IMAGE = (
    "python@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
)


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ContractError(f"required protected configuration is missing: {name}")
    if "\n" in value or "\r" in value:
        raise ContractError(f"configuration contains a newline: {name}")
    return value


def remote_options(identity: Path, known_hosts: Path) -> list[str]:
    return [
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-i", str(identity),
    ]


def download_offhost(
    *, remote: str, stamp: str, destination: Path, identity: Path, known_hosts: Path
) -> None:
    host, root = parse_remote(remote)
    remote_directory = f"{root}/{stamp}"
    options = remote_options(identity, known_hosts)
    listing = run_command(
        [
            "ssh", *options, host,
            (
                f"cd {shlex.quote(remote_directory)} && "
                "test -f SHA256SUMS && test -f STATUS.json && "
                "find . -maxdepth 1 -type f -name 'databases-*.tar.gz.gpg' -printf '%f\\n'"
            ),
        ],
        timeout=60,
    ).stdout.decode("utf-8", "replace").splitlines()
    encrypted_names = [line.strip() for line in listing if line.strip()]
    if len(encrypted_names) != 1:
        raise ContractError(
            f"off-host backup must contain exactly one encrypted bundle; found {len(encrypted_names)}"
        )
    for name in (encrypted_names[0], "SHA256SUMS", "STATUS.json"):
        run_command(
            ["scp", "-q", *options, f"{host}:{remote_directory}/{name}", str(destination / name)],
            timeout=1800,
        )


def verify_plaintext_manifest(extracted: Path) -> dict[str, Any]:
    checksum_contract = load_json(extracted / "PLAINTEXT-SHA256.json")
    if checksum_contract.get("schema") != "codestra.plaintext-checksums.v1":
        raise ContractError("unsupported plaintext checksum contract")
    expected_names: set[str] = {"PLAINTEXT-SHA256.json"}
    entries = checksum_contract.get("files")
    if not isinstance(entries, list) or not entries:
        raise ContractError("plaintext checksum contract has no files")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ContractError("plaintext checksum entry must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or Path(name).name != name:
            raise ContractError("plaintext checksum contains an unsafe member name")
        if name in expected_names:
            raise ContractError(f"plaintext checksum contains a duplicate member: {name}")
        expected_names.add(name)
        path = extracted / name
        if not path.is_file():
            raise ContractError(f"backup member is missing: {name}")
        if sha256_file(path) != entry.get("sha256"):
            raise ContractError(f"backup member checksum mismatch: {name}")
        if path.stat().st_size != entry.get("bytes"):
            raise ContractError(f"backup member size mismatch: {name}")
    actual_names = {path.name for path in extracted.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise ContractError(
            "plaintext bundle contains unlisted or missing members: "
            f"expected={sorted(expected_names)}, actual={sorted(actual_names)}"
        )
    manifest = load_json(extracted / "manifest.json")
    if manifest.get("schema") != "codestra.database-backup-manifest.v2":
        raise ContractError("unsupported database backup manifest")
    if manifest.get("environment") != "production":
        raise ContractError("backup manifest does not identify production")
    if manifest.get("production_business_writes_executed") is not False:
        raise ContractError("backup manifest does not preserve write safety")
    immutability = manifest.get("immutability_evidence")
    if not isinstance(immutability, dict) or immutability.get("status") != "PASS":
        raise ContractError("backup manifest lacks PASS immutable-retention evidence")
    if immutability.get("deletion_protection_tested") is not True:
        raise ContractError("backup manifest does not prove deletion protection")
    try:
        retention_until = datetime.fromisoformat(
            str(immutability["retention_until"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise ContractError("backup manifest immutable-retention timestamp is invalid") from exc
    if retention_until.tzinfo is None or retention_until <= datetime.now(timezone.utc):
        raise ContractError("backup manifest immutable retention is expired")
    return manifest


def docker(*args: str, timeout: int = 300, check: bool = True) -> bytes:
    return run_command(["docker", *args], timeout=timeout, check=check).stdout


def wait_postgres(container: str, image: str, password_file: Path) -> None:
    for _ in range(90):
        result = run_command(
            [
                "docker", "run", "--rm", "--network", f"container:{container}",
                "--entrypoint", "/bin/sh",
                "-v", f"{password_file}:/run/secrets/postgres_password:ro",
                image,
                "-c",
                (
                    'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; '
                    "exec pg_isready -h 127.0.0.1 -U postgres"
                ),
            ],
            timeout=20,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    raise ContractError("isolated restore PostgreSQL did not become ready")


def postgres_client(
    *, image: str, network: str, password_file: Path, args: list[str],
    mount: tuple[Path, str] | None = None, timeout: int = 900,
) -> bytes:
    command = [
        "docker", "run", "--rm", "--network", network,
        "--user", "1000:0", "--entrypoint", "/bin/sh",
        "-v", f"{password_file}:/run/secrets/postgres_password:ro",
    ]
    if mount is not None:
        command.extend(["-v", f"{mount[0]}:{mount[1]}:ro"])
    command.extend(
        [
            image,
            "-c",
            'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec "$@"',
            "sh", *args,
        ]
    )
    return run_command(command, timeout=timeout).stdout


def restore_postgres_databases(
    *, manifest: dict[str, Any], extracted: Path, image: str,
    network: str, password_file: Path,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    records: list[dict[str, Any]] = []
    application_databases: dict[str, str] = {}
    for entry in manifest.get("postgres_databases", []):
        source_id = require_safe_id(entry["id"], field="database id")
        restore_database = "restore_" + source_id.replace("-", "_")
        require_safe_id(restore_database, field="restore database")
        archive_name = entry["archive_member"]
        archive = extracted / archive_name
        if archive.name != archive_name or not archive.is_file():
            raise ContractError(f"database archive is missing: {source_id}")
        postgres_client(
            image=image,
            network=network,
            password_file=password_file,
            args=["createdb", "-h", "postgres", "-U", "postgres", restore_database],
        )
        postgres_client(
            image=image,
            network=network,
            password_file=password_file,
            mount=(extracted, "/restore"),
            args=[
                "pg_restore", "-h", "postgres", "-U", "postgres",
                "--no-owner", "--no-privileges", "--exit-on-error",
                "-d", restore_database, f"/restore/{archive_name}",
            ],
            timeout=1800,
        )
        output = postgres_client(
            image=image,
            network=network,
            password_file=password_file,
            args=[
                "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                "-h", "postgres", "-U", "postgres", "-d", restore_database,
                "-c",
                (
                    "select count(*) from information_schema.tables "
                    "where table_schema not in ('pg_catalog','information_schema')"
                ),
            ],
        ).decode().strip()
        table_count = int(output)
        source_count = int(entry.get("source_table_count", 0))
        if source_count > 0 and table_count == 0:
            raise ContractError(f"restored database contains no application tables: {source_id}")
        records.append(
            {
                "source_id": source_id,
                "restore_database": restore_database,
                "source_table_count": source_count,
                "restore_table_count": table_count,
                "status": "PASS",
            }
        )
        application = entry.get("application")
        if application:
            application_id = require_safe_id(str(application), field="application id")
            if application_id in application_databases:
                raise ContractError(
                    f"backup identifies duplicate application database: {application_id}"
                )
            application_databases[application_id] = restore_database
    if not records:
        raise ContractError("backup contains no PostgreSQL database archives")
    for required_application in (
        "keycloak", "n8n", "control-plane", "appolon", "beyvra-email", "email-reseller"
    ):
        if required_application not in application_databases:
            raise ContractError(
                f"backup does not identify required application database: {required_application}"
            )
    return records, application_databases


def verify_sqlite(extracted: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    import sqlite3

    records: list[dict[str, Any]] = []
    for entry in manifest.get("sqlite_databases", []):
        path = extracted / entry["archive_member"]
        if path.name != entry["archive_member"] or not path.is_file():
            raise ContractError(f"SQLite archive is missing: {entry.get('id')}")
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        if integrity != "ok" or quick != "ok":
            raise ContractError(f"SQLite integrity validation failed: {entry.get('id')}")
        records.append({"source_id": entry.get("id"), "status": "PASS"})
    return records


def verify_volume_archives(extracted: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for entry in manifest.get("volume_archives", []):
        archive_name = entry.get("archive_member")
        if not isinstance(archive_name, str):
            raise ContractError("volume archive member name is invalid")
        path = extracted / archive_name
        if path.name != archive_name or not path.is_file():
            raise ContractError(f"volume archive is missing: {entry.get('id')}")
        target_id = require_safe_id(str(entry.get("id", "")), field="volume archive id")
        destination = extracted / f"volume-restore-{target_id}"
        safe_extract_tar(path, destination)
        files = [candidate for candidate in destination.rglob("*") if candidate.is_file()]
        directories = [candidate for candidate in destination.rglob("*") if candidate.is_dir()]
        if not files and not directories:
            raise ContractError(f"volume archive restored no members: {target_id}")
        records.append(
            {
                "source_id": target_id,
                "file_count": len(files),
                "directory_count": len(directories),
                "restored_bytes": sum(candidate.stat().st_size for candidate in files),
                "status": "PASS",
                "extracted_in_isolation": True,
            }
        )
    return records


def verify_protected_configuration(
    extracted: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    record = manifest.get("protected_configuration")
    if not isinstance(record, dict):
        raise ContractError("backup manifest lacks protected configuration evidence")
    archive_name = record.get("archive_member")
    if not isinstance(archive_name, str):
        raise ContractError("protected configuration archive name is invalid")
    archive = extracted / archive_name
    if archive.name != archive_name or not archive.is_file():
        raise ContractError("protected configuration archive is missing")
    destination = extracted / "protected-configuration-restore"
    safe_extract_tar(archive, destination)
    files = [candidate for candidate in destination.rglob("*") if candidate.is_file()]
    if not files:
        raise ContractError("protected configuration restore contains no files")
    return {
        "status": "PASS",
        "file_count": len(files),
        "restored_bytes": sum(candidate.stat().st_size for candidate in files),
        "applied_to_host": False,
    }


def wait_keycloak(*, network: str, python_image: str) -> str:
    probe = r"""
import urllib.request
for url in ('http://keycloak:9000/health/ready','http://keycloak:8080/health/ready'):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status == 200:
                print(url)
                raise SystemExit(0)
    except Exception:
        pass
raise SystemExit(1)
"""
    for _ in range(120):
        result = run_command(
            ["docker", "run", "--rm", "--network", network, python_image, "python", "-c", probe],
            timeout=20,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.decode().strip()
        time.sleep(2)
    raise ContractError("Keycloak did not become ready against the restored database")


def start_keycloak_restore(
    *, network: str, database: str, password_file: Path,
    keycloak_image: str, python_image: str, name: str,
) -> dict[str, Any]:
    docker(
        "run", "-d", "--name", name,
        "--network", network, "--network-alias", "keycloak",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--tmpfs", "/opt/keycloak/data:rw,noexec,nosuid,size=256m,uid=1000,gid=0,mode=0770",
        "--user", "1000:0", "--entrypoint", "/bin/sh",
        "-v", f"{password_file}:/run/secrets/postgres_password:ro",
        "-e", "KC_DB=postgres",
        "-e", f"KC_DB_URL=jdbc:postgresql://postgres:5432/{database}",
        "-e", "KC_DB_USERNAME=postgres",
        "-e", "KC_HEALTH_ENABLED=true",
        "-e", "KC_HTTP_ENABLED=true",
        "-e", "KC_HOSTNAME_STRICT=false",
        keycloak_image,
        "-c",
        (
            'export KC_DB_PASSWORD="$(cat /run/secrets/postgres_password)"; '
            "exec /opt/keycloak/bin/kc.sh start-dev"
        ),
        timeout=120,
    )
    endpoint = wait_keycloak(network=network, python_image=python_image)
    return {"status": "PASS", "ready_endpoint": endpoint, "public_ports": 0}


def prove_n8n_credential_recovery(
    *, network: str, database: str, password_file: Path,
    n8n_image: str, encryption_key_file: Path, name: str, minimum_credentials: int,
) -> dict[str, Any]:
    """Prove n8n credential decryption without retaining or emitting values."""
    if minimum_credentials < 1:
        raise ContractError("n8n minimum credential count must be at least one")
    validate_protected_file(encryption_key_file, owner_uid=0)
    shell = r"""
set -eu
umask 077
mkdir -p /tmp/n8n-user
export N8N_USER_FOLDER=/tmp/n8n-user
export N8N_ENCRYPTION_KEY="$(cat /run/secrets/n8n_encryption_key)"
export DB_POSTGRESDB_PASSWORD="$(cat /run/secrets/postgres_password)"
export N8N_DIAGNOSTICS_ENABLED=false
export N8N_PERSONALIZATION_ENABLED=false
export N8N_VERSION_NOTIFICATIONS_ENABLED=false
export N8N_TEMPLATES_ENABLED=false
output=/tmp/decrypted-credentials.json
log=/tmp/n8n-export.log
cleanup() { rm -f "$output" "$log"; }
trap cleanup EXIT HUP INT TERM
if ! n8n export:credentials --all --decrypted --output="$output" >"$log" 2>&1; then
  echo 'n8n credential export failed' >&2
  exit 1
fi
node - "$output" "$CODESTRA_N8N_MINIMUM_CREDENTIAL_COUNT" <<'NODE'
const fs = require('fs');
const path = process.argv[2];
const minimum = Number(process.argv[3]);
const text = fs.readFileSync(path, 'utf8');
const payload = JSON.parse(text);
const count = Array.isArray(payload) ? payload.length : (payload && typeof payload === 'object' ? 1 : 0);
if (!Number.isInteger(count) || count < minimum) process.exit(3);
process.stdout.write(`CREDENTIAL_COUNT=${count}\n`);
NODE
"""
    try:
        output = docker(
            "run", "--rm", "--name", name, "--network", network,
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--user", "0:0", "--entrypoint", "/bin/sh",
            "-v", f"{encryption_key_file}:/run/secrets/n8n_encryption_key:ro",
            "-v", f"{password_file}:/run/secrets/postgres_password:ro",
            "-e", "DB_TYPE=postgresdb",
            "-e", "DB_POSTGRESDB_HOST=postgres",
            "-e", "DB_POSTGRESDB_PORT=5432",
            "-e", f"DB_POSTGRESDB_DATABASE={database}",
            "-e", "DB_POSTGRESDB_USER=postgres",
            "-e", "DB_POSTGRESDB_SCHEMA=public",
            "-e", f"CODESTRA_N8N_MINIMUM_CREDENTIAL_COUNT={minimum_credentials}",
            n8n_image, "-c", shell,
            timeout=900,
        ).decode("utf-8", "replace").strip()
    finally:
        docker("rm", "-f", name, check=False)
    if not output.startswith("CREDENTIAL_COUNT="):
        raise ContractError("n8n credential recovery returned an unexpected result")
    try:
        count = int(output.split("=", 1)[1])
    except ValueError as exc:
        raise ContractError("n8n credential recovery count is not numeric") from exc
    if count < minimum_credentials:
        raise ContractError("n8n credential recovery did not meet the required count")
    return {
        "status": "PASS",
        "credential_count": count,
        "decrypted_values_recorded": False,
        "external_network_egress": False,
        "public_ports": 0,
        "workflow_execution_started": False,
    }


def cleanup_restore_resources(
    *, network: str, volume: str, container_names: list[str], verify: bool
) -> int:
    """Remove disposable resources and optionally prove no residual remains."""
    for name in container_names:
        docker("rm", "-f", name, check=False)
    docker("volume", "rm", volume, check=False)
    docker("network", "rm", network, check=False)
    residual = 0
    if verify:
        resources = [("container", item) for item in container_names]
        resources.extend([("volume", volume), ("network", network)])
        for kind, name in resources:
            command = ["inspect", name] if kind == "container" else [kind, "inspect", name]
            result = run_command(["docker", *command], timeout=30, check=False)
            if result.returncode == 0:
                residual += 1
        if residual:
            raise ContractError(f"isolated restore left {residual} residual Docker resources")
    return residual


def publish_metrics(
    path: Path, *, success: bool, timestamp: int, duration: float,
    keycloak: bool, n8n_credentials: bool,
) -> None:
    write_prometheus_textfile(
        path,
        [
            "# HELP codestra_database_restore_last_success_timestamp_seconds Unix timestamp of the last successful isolated restore.",
            "# TYPE codestra_database_restore_last_success_timestamp_seconds gauge",
            f"codestra_database_restore_last_success_timestamp_seconds {timestamp if success else 0}",
            "# HELP codestra_database_restore_last_run_success Whether the latest isolated restore succeeded.",
            "# TYPE codestra_database_restore_last_run_success gauge",
            f"codestra_database_restore_last_run_success {1 if success else 0}",
            "# HELP codestra_keycloak_restored_startup_success Whether Keycloak started against the restored identity database.",
            "# TYPE codestra_keycloak_restored_startup_success gauge",
            f"codestra_keycloak_restored_startup_success {1 if keycloak else 0}",
            "# HELP codestra_n8n_credential_recovery_success Whether n8n decrypted restored credentials without exposing values.",
            "# TYPE codestra_n8n_credential_recovery_success gauge",
            f"codestra_n8n_credential_recovery_success {1 if n8n_credentials else 0}",
            "# HELP codestra_database_restore_last_duration_seconds Duration of the latest restore rehearsal.",
            "# TYPE codestra_database_restore_last_duration_seconds gauge",
            f"codestra_database_restore_last_duration_seconds {duration:.3f}",
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", required=True)
    return parser.parse_args()


def main() -> int:
    parse_args()
    started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    metrics = Path(
        os.environ.get(
            "CODESTRA_DATABASE_RESTORE_METRICS_FILE",
            "/var/lib/node_exporter/textfile_collector/codestra_database_restore.prom",
        )
    )
    network = f"codestra-database-restore-{stamp.lower()}"
    postgres_name = f"codestra-database-restore-postgres-{stamp.lower()}"
    keycloak_name = f"codestra-keycloak-restore-{stamp.lower()}"
    n8n_name = f"codestra-n8n-credential-recovery-{stamp.lower()}"
    volume = f"codestra-database-restore-data-{stamp.lower()}"
    try:
        for executable in ("docker", "gpg", "ssh", "scp"):
            require_executable(executable)
        remote = required("CODESTRA_DATABASE_RESTORE_REMOTE")
        backup_stamp = os.environ.get("CODESTRA_DATABASE_RESTORE_STAMP", "").strip()
        if not backup_stamp:
            stamp_file = Path(required("CODESTRA_DATABASE_RESTORE_STAMP_FILE"))
            validate_protected_file(stamp_file, owner_uid=0)
            backup_stamp = stamp_file.read_text(encoding="utf-8").strip()
        try:
            datetime.strptime(backup_stamp, "%Y%m%dT%H%M%SZ")
        except ValueError as exc:
            raise ContractError("advertised restore stamp has an invalid format") from exc
        identity = Path(required("CODESTRA_DATABASE_RESTORE_SSH_IDENTITY"))
        known_hosts = Path(required("CODESTRA_DATABASE_RESTORE_KNOWN_HOSTS"))
        gpg_home = Path(required("CODESTRA_DATABASE_RESTORE_GPG_HOME"))
        expected_signing_fingerprint = required(
            "CODESTRA_DATABASE_RESTORE_GPG_SIGNING_FINGERPRINT"
        ).upper()
        if not re.fullmatch(r"[0-9A-F]{40,64}", expected_signing_fingerprint):
            raise ContractError("restore signing fingerprint must be 40-64 hexadecimal characters")
        validate_protected_file(identity, owner_uid=0)
        validate_protected_file(known_hosts, owner_uid=0)
        if not gpg_home.is_dir():
            raise ContractError("restore GPG home is unavailable")
        postgres_image = require_digest_image(
            os.environ.get("CODESTRA_POSTGRES_RESTORE_IMAGE", DEFAULT_POSTGRES_IMAGE),
            field="CODESTRA_POSTGRES_RESTORE_IMAGE",
        )
        python_image = require_digest_image(
            os.environ.get("CODESTRA_RESTORE_PYTHON_IMAGE", DEFAULT_PYTHON_IMAGE),
            field="CODESTRA_RESTORE_PYTHON_IMAGE",
        )
        keycloak_image = require_digest_image(
            required("CODESTRA_KEYCLOAK_RESTORE_IMAGE"),
            field="CODESTRA_KEYCLOAK_RESTORE_IMAGE",
        )
        n8n_image = require_digest_image(
            required("CODESTRA_N8N_RESTORE_IMAGE"),
            field="CODESTRA_N8N_RESTORE_IMAGE",
        )
        n8n_key_file = Path(required("CODESTRA_N8N_RECOVERY_ENCRYPTION_KEY_FILE"))
        validate_protected_file(n8n_key_file, owner_uid=0)
        n8n_minimum_credentials = int(
            os.environ.get("CODESTRA_N8N_MINIMUM_CREDENTIAL_COUNT", "1")
        )
        if n8n_minimum_credentials < 1 or n8n_minimum_credentials > 100000:
            raise ContractError("n8n minimum credential count is outside the allowed range")
        evidence_root = Path(
            os.environ.get(
                "CODESTRA_DATABASE_RESTORE_ROOT",
                "/opt/codestra/evidence/database-restore",
            )
        )
        if not evidence_root.is_absolute():
            raise ContractError("CODESTRA_DATABASE_RESTORE_ROOT must be absolute")
        evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        final = evidence_root / stamp
        if final.exists():
            raise ContractError("restore evidence timestamp collision")

        with tempfile.TemporaryDirectory(prefix=f".restore-{stamp}-", dir=evidence_root) as temporary:
            work = Path(temporary)
            os.chmod(work, 0o700)
            download_offhost(
                remote=remote,
                stamp=backup_stamp,
                destination=work,
                identity=identity,
                known_hosts=known_hosts,
            )
            status = load_json(work / "STATUS.json")
            if (
                status.get("status") != "PASS"
                or status.get("off_host_copy") != "PASS"
                or status.get("immutable_retention") != "PASS"
                or status.get("checksum") != "PASS"
                or status.get("encryption") != "PASS"
            ):
                raise ContractError("off-host backup status is not fully PASS")
            if status.get("timestamp") != backup_stamp:
                raise ContractError("off-host status timestamp does not match requested backup")
            if str(status.get("gpg_signing_fingerprint", "")).upper() != expected_signing_fingerprint:
                raise ContractError("off-host status signing fingerprint does not match policy")
            encrypted_candidates = list(work.glob("databases-*.tar.gz.gpg"))
            if len(encrypted_candidates) != 1:
                raise ContractError("downloaded backup has an ambiguous encrypted artifact")
            encrypted = encrypted_candidates[0]
            checksum_lines = (work / "SHA256SUMS").read_text().splitlines()
            if len(checksum_lines) != 1:
                raise ContractError("encrypted checksum manifest has an unexpected shape")
            expected_digest, expected_name = checksum_lines[0].split(maxsplit=1)
            expected_name = expected_name.lstrip("* ")
            if expected_name != encrypted.name or sha256_file(encrypted) != expected_digest:
                raise ContractError("downloaded encrypted backup checksum mismatch")
            if status.get("encrypted_sha256") != expected_digest:
                raise ContractError("off-host status encrypted digest does not match checksum manifest")
            if status.get("off_host_sha256") != expected_digest:
                raise ContractError("off-host checksum readback evidence does not match downloaded artifact")
            plaintext = work / "databases.tar.gz"
            signature_status = run_command(
                [
                    "gpg", "--homedir", str(gpg_home), "--batch", "--yes",
                    "--lock-never", "--no-auto-check-trustdb", "--status-fd", "1",
                    "--output", str(plaintext), "--decrypt", str(encrypted),
                ],
                timeout=1800,
            ).stdout.decode("utf-8", "replace")
            valid_fingerprints = {
                line.split()[2].upper()
                for line in signature_status.splitlines()
                if line.startswith("[GNUPG:] VALIDSIG ") and len(line.split()) >= 3
            }
            if expected_signing_fingerprint not in valid_fingerprints:
                raise ContractError("encrypted backup does not have the required valid GPG signature")
            extracted = work / "extracted"
            safe_extract_tar(plaintext, extracted)
            manifest = verify_plaintext_manifest(extracted)
            if manifest.get("timestamp") != backup_stamp:
                raise ContractError("backup manifest timestamp does not match requested off-host stamp")

            password = secrets.token_urlsafe(36)
            password_file = work / "restore-postgres-password"
            atomic_write(password_file, (password + "\n").encode("utf-8"), mode=0o640)
            docker("network", "create", "--internal", network)
            docker("volume", "create", volume)
            docker(
                "run", "-d", "--name", postgres_name,
                "--network", network, "--network-alias", "postgres",
                "-e", "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password",
                "-v", f"{password_file}:/run/secrets/postgres_password:ro",
                "-v", f"{volume}:/var/lib/postgresql/data",
                postgres_image,
                timeout=120,
            )
            wait_postgres(postgres_name, postgres_image, password_file)
            postgres_records, application_databases = restore_postgres_databases(
                manifest=manifest,
                extracted=extracted,
                image=postgres_image,
                network=network,
                password_file=password_file,
            )
            sqlite_records = verify_sqlite(extracted, manifest)
            volume_records = verify_volume_archives(extracted, manifest)
            protected_configuration = verify_protected_configuration(extracted, manifest)
            keycloak_record = start_keycloak_restore(
                network=network,
                database=application_databases["keycloak"],
                password_file=password_file,
                keycloak_image=keycloak_image,
                python_image=python_image,
                name=keycloak_name,
            )
            n8n_record = prove_n8n_credential_recovery(
                network=network,
                database=application_databases["n8n"],
                password_file=password_file,
                n8n_image=n8n_image,
                encryption_key_file=n8n_key_file,
                name=n8n_name,
                minimum_credentials=n8n_minimum_credentials,
            )
            residual_resources = cleanup_restore_resources(
                network=network,
                volume=volume,
                container_names=[n8n_name, keycloak_name, postgres_name],
                verify=True,
            )
            result = {
                "schema": "codestra.database-restore-result.v2",
                "status": "PASS",
                "timestamp": stamp,
                "source_backup_timestamp": backup_stamp,
                "source": "OFF_HOST_ENCRYPTED_COPY",
                "source_encrypted_sha256": expected_digest,
                "gpg_signature": "PASS",
                "gpg_signing_fingerprint": expected_signing_fingerprint,
                "postgres_databases": postgres_records,
                "sqlite_databases": sqlite_records,
                "volume_archives": volume_records,
                "protected_configuration": protected_configuration,
                "application_databases": application_databases,
                "keycloak_restored_startup": keycloak_record,
                "n8n_credential_recovery": n8n_record,
                "selective_recovery_database_proof": {
                    application: {"database": database, "status": "PASS"}
                    for application, database in application_databases.items()
                    if application in {
                        "appolon", "beyvra-email", "email-reseller", "control-plane"
                    }
                },
                "restore_network_internal": True,
                "restore_public_ports": 0,
                "restore_residual_resources": residual_resources,
                "production_business_writes_executed": False,
                "duration_seconds": round(time.monotonic() - started, 3),
            }
            final.mkdir(mode=0o700)
            atomic_write_json(final / "RESTORE-RESULT.json", result)
            atomic_write(
                final / "SHA256SUMS",
                f"{sha256_file(final / 'RESTORE-RESULT.json')}  RESTORE-RESULT.json\n".encode(),
                mode=0o600,
            )
            atomic_write(evidence_root / "LAST_SUCCESS", f"{stamp}\n".encode(), mode=0o600)
            publish_metrics(
                metrics,
                success=True,
                timestamp=int(datetime.now(timezone.utc).timestamp()),
                duration=time.monotonic() - started,
                keycloak=True,
                n8n_credentials=True,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        try:
            publish_metrics(
                metrics,
                success=False,
                timestamp=0,
                duration=time.monotonic() - started,
                keycloak=False,
                n8n_credentials=False,
            )
        except Exception:
            pass
        print("DATABASE_RESTORE=FAIL", file=sys.stderr)
        print(f"DATABASE_RESTORE_ERROR={str(exc)[:1000]}", file=sys.stderr)
        return 1
    finally:
        try:
            cleanup_restore_resources(
                network=network,
                volume=volume,
                container_names=[n8n_name, keycloak_name, postgres_name],
                verify=False,
            )
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
