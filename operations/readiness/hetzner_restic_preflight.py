#!/usr/bin/env python3
"""Validate a protected Hetzner backup profile; optionally read repository metadata.

This command never initializes, uploads, prunes, restores, or switches a repository.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess

FIELDS = {
    "schema_version", "region", "bucket", "prefix",
    "access_key_id_file", "secret_access_key_file", "restic_password_file",
}
REGIONS = {"fsn1", "nbg1", "hel1"}
DEFAULT_PROFILE = Path("/etc/codestra/backup/hetzner-restic.json")


class ProfileError(ValueError):
    """A bounded configuration error that contains no supplied values."""


def protected_text(path: Path) -> str:
    if not path.is_absolute() or ".." in path.parts:
        raise ProfileError("invalid_protected_path")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077):
                raise ProfileError("unsafe_protected_file")
            content = source.read(16385)
    except OSError:
        raise ProfileError("protected_file_unavailable") from None
    if not content or len(content) > 16384:
        raise ProfileError("invalid_protected_file_size")
    try:
        return content.decode("utf-8")
    except UnicodeError:
        raise ProfileError("invalid_protected_file_encoding") from None


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError("duplicate_profile_field")
        result[key] = value
    return result


def load_profile(path: Path) -> dict:
    try:
        profile = json.loads(protected_text(path), object_pairs_hook=unique_fields)
    except (json.JSONDecodeError, RecursionError):
        raise ProfileError("invalid_profile_json") from None
    if not isinstance(profile, dict) or set(profile) != FIELDS:
        raise ProfileError("invalid_profile_fields")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ProfileError("invalid_profile_version")
    if any(not isinstance(profile[key], str) for key in FIELDS - {"schema_version"}):
        raise ProfileError("invalid_profile_value_type")
    if profile["region"] not in REGIONS:
        raise ProfileError("unsupported_hetzner_region")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", profile["bucket"]):
        raise ProfileError("invalid_bucket")
    prefix = profile["prefix"]
    if (len(prefix) > 160 or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]*(/[A-Za-z0-9][A-Za-z0-9_-]*)*", prefix)):
        raise ProfileError("invalid_repository_prefix")
    for key in FIELDS:
        if key.endswith("_file"):
            candidate = Path(profile[key])
            if not candidate.is_absolute() or ".." in candidate.parts:
                raise ProfileError("invalid_protected_path")
    return profile


def repository(profile: dict) -> str:
    return (f's3:https://{profile["region"]}.your-objectstorage.com/'
            f'{profile["bucket"]}/{profile["prefix"]}')


def credentials(profile: dict) -> dict:
    values = {}
    for key in ("access_key_id_file", "secret_access_key_file", "restic_password_file"):
        value = protected_text(Path(profile[key])).strip()
        if not value or any(character in value for character in "\r\n\x00"):
            raise ProfileError("invalid_credential_file")
        if value.startswith(("REPLACE_", "CHANGEME", "<")):
            raise ProfileError("placeholder_credential")
        values[key] = value
    # A minimal environment prevents inherited B2 credentials, session tokens,
    # alternate endpoints, proxies, password commands or TLS overrides leaking in.
    return {
        "PATH": os.defpath,
        "RESTIC_REPOSITORY": repository(profile),
        "RESTIC_PASSWORD_FILE": profile["restic_password_file"],
        "AWS_ACCESS_KEY_ID": values["access_key_id_file"],
        "AWS_SECRET_ACCESS_KEY": values["secret_access_key_file"],
        "AWS_DEFAULT_REGION": profile["region"],
        "AWS_EC2_METADATA_DISABLED": "true",
    }


def inspect_profile(path: Path, check_repository: bool = False) -> dict:
    profile = load_profile(path)
    environment = credentials(profile)
    result = {
        "provider": "hetzner_object_storage",
        "region": profile["region"],
        "bucket": profile["bucket"],
        "prefix": profile["prefix"],
        "repository": repository(profile),
        "configuration": "valid",
        "repository_access": "not_checked",
        "cutover_performed": False,
        "upload_verified": False,
        "restore_verified": False,
    }
    if not check_repository:
        return result
    try:
        process = subprocess.run(
            ["/usr/bin/restic", "--no-cache", "--no-lock", "snapshots", "--json"],
            env=environment, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        result["repository_access"] = "failed"
        result["reason"] = "repository_probe_unavailable_or_timeout"
        return result
    if process.returncode:
        result["repository_access"] = "failed"
        result["reason"] = "repository_read_or_decryption_failed"
        return result
    try:
        snapshots = json.loads(process.stdout)
        if not isinstance(snapshots, list) or any(
                not isinstance(item, dict)
                or not re.fullmatch(r"[0-9a-f]{64}", item.get("id", "")
                                   if isinstance(item.get("id", ""), str) else "")
                for item in snapshots):
            raise ValueError
    except (ValueError, RecursionError):
        result["repository_access"] = "failed"
        result["reason"] = "invalid_repository_response"
        return result
    result["repository_access"] = "readable"
    result["snapshot_count"] = len(snapshots)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--check-repository", action="store_true",
                        help="Read existing snapshot metadata; never initialize a repository.")
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise ProfileError("root_required")
        result = inspect_profile(args.profile, args.check_repository)
    except ProfileError as error:
        print(json.dumps({"configuration": "invalid", "reason": str(error),
                          "cutover_performed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 3 if result["repository_access"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
