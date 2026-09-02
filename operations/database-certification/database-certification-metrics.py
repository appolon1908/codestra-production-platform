#!/usr/bin/env python3
"""Publish fail-closed backup/restore freshness metrics from durable evidence."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runtime_contract import ContractError, load_json, write_prometheus_textfile


def parse_stamp(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def valid_backup(payload: dict[str, Any], stamp: str) -> bool:
    return all(
        (
            payload.get("status") == "PASS",
            payload.get("timestamp") == stamp,
            payload.get("encryption") == "PASS",
            payload.get("checksum") == "PASS",
            payload.get("off_host_copy") == "PASS",
            payload.get("immutable_retention") == "PASS",
            payload.get("production_business_writes_executed") is False,
        )
    )


def valid_restore(payload: dict[str, Any], stamp: str) -> bool:
    return all(
        (
            payload.get("status") == "PASS",
            payload.get("timestamp") == stamp,
            payload.get("source") == "OFF_HOST_ENCRYPTED_COPY",
            payload.get("gpg_signature") == "PASS",
            payload.get("keycloak_restored_startup", {}).get("status") == "PASS",
            payload.get("n8n_credential_recovery", {}).get("status") == "PASS",
            payload.get("protected_configuration", {}).get("status") == "PASS",
            payload.get("restore_network_internal") is True,
            payload.get("restore_public_ports") == 0,
            payload.get("restore_residual_resources") == 0,
            payload.get("production_business_writes_executed") is False,
            bool(payload.get("postgres_databases")),
            all(item.get("status") == "PASS" for item in payload.get("postgres_databases", [])),
            all(item.get("status") == "PASS" for item in payload.get("volume_archives", [])),
        )
    )


def evidence_state(
    root: Path,
    result_name: str,
    validator: Callable[[dict[str, Any], str], bool],
) -> tuple[int, int, str, dict[str, Any]]:
    marker = root / "LAST_SUCCESS"
    if not marker.is_file():
        return 0, 0, "MISSING", {}
    stamp = marker.read_text(encoding="utf-8").strip()
    parsed = parse_stamp(stamp)
    result_path = root / stamp / result_name
    if not result_path.is_file():
        return 0, 0, "MISSING_RESULT", {}
    payload = load_json(result_path)
    success = int(validator(payload, stamp))
    return int(parsed.timestamp()), success, stamp, payload


def main() -> int:
    backup_root = Path(
        os.environ.get(
            "CODESTRA_DATABASE_BACKUP_ROOT",
            "/opt/codestra/backups/database-certification",
        )
    )
    restore_root = Path(
        os.environ.get(
            "CODESTRA_DATABASE_RESTORE_ROOT",
            "/opt/codestra/evidence/database-restore",
        )
    )
    output = Path(
        os.environ.get(
            "CODESTRA_DATABASE_CERTIFICATION_METRICS_FILE",
            "/var/lib/node_exporter/textfile_collector/codestra_database_certification.prom",
        )
    )
    try:
        backup_ts, backup_ok, _, backup = evidence_state(
            backup_root, "STATUS.json", valid_backup
        )
        restore_ts, restore_ok, _, restore = evidence_state(
            restore_root, "RESTORE-RESULT.json", valid_restore
        )
        keycloak_ok = int(
            restore_ok
            and restore.get("keycloak_restored_startup", {}).get("status") == "PASS"
        )
        n8n_ok = int(
            restore_ok
            and restore.get("n8n_credential_recovery", {}).get("status") == "PASS"
        )
        offhost_ok = int(backup_ok and backup.get("off_host_copy") == "PASS")
        immutable_ok = int(backup_ok and backup.get("immutable_retention") == "PASS")
        now = int(datetime.now(timezone.utc).timestamp())
        lines = [
            "# HELP codestra_database_backup_last_success_timestamp_seconds Unix timestamp of the last successful encrypted off-host backup.",
            "# TYPE codestra_database_backup_last_success_timestamp_seconds gauge",
            f"codestra_database_backup_last_success_timestamp_seconds {backup_ts}",
            "# HELP codestra_database_backup_age_seconds Age of the last successful backup.",
            "# TYPE codestra_database_backup_age_seconds gauge",
            f"codestra_database_backup_age_seconds {max(0, now - backup_ts) if backup_ts else 0}",
            "# HELP codestra_database_backup_evidence_valid Whether all advertised backup evidence is valid.",
            "# TYPE codestra_database_backup_evidence_valid gauge",
            f"codestra_database_backup_evidence_valid {backup_ok}",
            "# HELP codestra_database_backup_offhost_verified Whether remote checksum readback passed.",
            "# TYPE codestra_database_backup_offhost_verified gauge",
            f"codestra_database_backup_offhost_verified {offhost_ok}",
            "# HELP codestra_database_backup_immutable_retention_verified Whether immutable retention evidence is current and PASS.",
            "# TYPE codestra_database_backup_immutable_retention_verified gauge",
            f"codestra_database_backup_immutable_retention_verified {immutable_ok}",
            "# HELP codestra_database_restore_last_success_timestamp_seconds Unix timestamp of the last successful isolated restore.",
            "# TYPE codestra_database_restore_last_success_timestamp_seconds gauge",
            f"codestra_database_restore_last_success_timestamp_seconds {restore_ts}",
            "# HELP codestra_database_restore_age_seconds Age of the last successful isolated restore.",
            "# TYPE codestra_database_restore_age_seconds gauge",
            f"codestra_database_restore_age_seconds {max(0, now - restore_ts) if restore_ts else 0}",
            "# HELP codestra_database_restore_evidence_valid Whether the full isolated restore evidence is valid.",
            "# TYPE codestra_database_restore_evidence_valid gauge",
            f"codestra_database_restore_evidence_valid {restore_ok}",
            "# HELP codestra_keycloak_restored_startup_success Whether Keycloak started against restored identity data.",
            "# TYPE codestra_keycloak_restored_startup_success gauge",
            f"codestra_keycloak_restored_startup_success {keycloak_ok}",
            "# HELP codestra_n8n_credential_recovery_success Whether n8n decrypted restored credentials without exposing values.",
            "# TYPE codestra_n8n_credential_recovery_success gauge",
            f"codestra_n8n_credential_recovery_success {n8n_ok}",
        ]
        write_prometheus_textfile(output, lines)
        print("DATABASE_CERTIFICATION_METRICS=PASS")
        return 0
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        try:
            write_prometheus_textfile(
                output,
                [
                    "codestra_database_backup_evidence_valid 0",
                    "codestra_database_backup_offhost_verified 0",
                    "codestra_database_backup_immutable_retention_verified 0",
                    "codestra_database_restore_evidence_valid 0",
                    "codestra_keycloak_restored_startup_success 0",
                    "codestra_n8n_credential_recovery_success 0",
                ],
            )
        except Exception:
            pass
        print(f"DATABASE_CERTIFICATION_METRICS=FAIL:{str(exc)[:800]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
