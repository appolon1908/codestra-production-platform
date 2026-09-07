#!/usr/bin/env python3
"""Fail-closed validation for the reviewed Server A installation record."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

FIELDS = {
    "operator_public_key": re.compile(r"^/home/codestra-admin/operator-current\.[A-Za-z0-9]+\.pub$"),
    "protected_commit": re.compile(r"^[0-9a-f]{40}$"),
    "image_digest": re.compile(r"^sha256:[0-9a-f]{64}$"),
    "change_id": re.compile(r"^CHG-[0-9]{8}-CODESTRA-PRODUCTION-ACTIVATION-[0-9]{2}$"),
    "maintenance_date": re.compile(r"^20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])$"),
    "control_plane_archive_sha256": re.compile(r"^[0-9a-f]{64}$"),
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
TARGET_DIGEST_FIELDS = (
    "release_archive_sha256",
    "release_manifest_sha256",
    "installer_sha256",
    "launcher_sha256",
    "embedded_installation_record_sha256",
    "trust_anchor_sha256",
)


def validate(record: dict, require_approved: bool = True) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != "codestra.server-a-operator-installation-record.v1":
        errors.append("invalid schema_version")
    if record.get("mode") != "preserve-existing-sudoers":
        errors.append("installation mode must preserve existing sudoers")
    if not HEX40.fullmatch(str(record.get("reference_release", ""))):
        errors.append("invalid reference release")
    target = record.get("target_release") or {}
    arguments = record.get("arguments") or {}
    fingerprint = record.get("operator_public_key_fingerprint") or {}
    if require_approved and (not fingerprint.get("value") or not fingerprint.get("approval")):
        errors.append("operator_public_key_fingerprint is not approved")
    if fingerprint.get("value") is not None and not re.fullmatch(
        r"^SHA256:[A-Za-z0-9+/]{43}$", str(fingerprint["value"])
    ):
        errors.append("operator_public_key_fingerprint is invalid")
    if not fingerprint.get("source"):
        errors.append("operator_public_key_fingerprint.source is required")
    for name in ("protected_commit", *TARGET_DIGEST_FIELDS, "approval"):
        if require_approved and not target.get(name):
            errors.append(f"target_release.{name} is not approved")
    # The launcher calls this validator without JSON Schema validation. Do not
    # coerce strings, numbers or containers into signature-verification evidence.
    signature_verified = target.get("manifest_signature_verified")
    if signature_verified is not None and not isinstance(signature_verified, bool):
        errors.append("target_release.manifest_signature_verified must be a boolean")
    if require_approved and signature_verified is not True:
        errors.append("target_release.manifest_signature_verified must be literal true")
    for name in TARGET_DIGEST_FIELDS:
        value = target.get(name)
        if value is not None and not HEX64.fullmatch(str(value)):
            errors.append(f"target_release.{name} is invalid")
    if target.get("protected_commit") is not None and not HEX40.fullmatch(str(target["protected_commit"])):
        errors.append("target_release.protected_commit is invalid")
    identity = record.get("server_a_identity") or {}
    expected_identity = {
        "hostname": "middleware",
        "primary_ipv4": "65.109.65.169",
        "observed_as": "codestra-admin",
        "public_key_metadata": "root:root mode=0600 links=1 bytes=81 path=/home/codestra-admin/operator-current.tR55n3.pub",
    }
    if identity != expected_identity:
        errors.append("server_a_identity does not match the read-only inventory")
    for name, pattern in FIELDS.items():
        item = arguments.get(name) or {}
        value = item.get("value")
        if require_approved and (value is None or not item.get("approval")):
            errors.append(f"arguments.{name} is not approved")
        if value is not None and not pattern.fullmatch(str(value)):
            errors.append(f"arguments.{name} is invalid")
        if not item.get("source"):
            errors.append(f"arguments.{name}.source is required")
    maintenance_date = arguments.get("maintenance_date", {}).get("value")
    if maintenance_date is not None and FIELDS["maintenance_date"].fullmatch(str(maintenance_date)):
        try:
            dt.date.fromisoformat(str(maintenance_date))
        except ValueError:
            errors.append("arguments.maintenance_date is not a calendar date")
    if target.get("protected_commit") and arguments.get("protected_commit", {}).get("value") != target["protected_commit"]:
        errors.append("protected commit argument does not match target release")
    control_digest = arguments.get("control_plane_archive_sha256", {}).get("value")
    # All package-related SHA-256 fields share one list so adding a required
    # digest cannot omit it from the control-plane substitution guard.
    non_control_digests = [target.get(name) for name in TARGET_DIGEST_FIELDS]
    image_digest = arguments.get("image_digest", {}).get("value")
    if isinstance(image_digest, str):
        non_control_digests.append(image_digest.removeprefix("sha256:"))
    if control_digest and control_digest in non_control_digests:
        errors.append("control-plane archive checksum must not reuse a non-control-plane digest")
    control_source = str(arguments.get("control_plane_archive_sha256", {}).get("source", "")).lower()
    if control_digest and ("installer checksum" in control_source or "release-package checksum" in control_source):
        errors.append("control-plane archive checksum has invalid authority")
    expected_status = "approved" if require_approved else "incomplete"
    if record.get("status") != expected_status:
        errors.append(f"record status must be {expected_status}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    errors = validate(record, require_approved=not args.allow_incomplete)
    for error in errors:
        print(f"INSTALLATION_RECORD_ERROR={error}")
    if errors:
        return 2
    print("INSTALLATION_RECORD_STATUS=" + ("INCOMPLETE" if args.allow_incomplete else "APPROVED"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
