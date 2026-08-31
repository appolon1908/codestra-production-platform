#!/usr/bin/python3
"""Rollback or remove the validator without touching Klyrow application state."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

from install_klyrow_production_validator_compat import mapped, restore_backups


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--simulator-root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if os.geteuid() != 0 or not re.fullmatch(r"[0-9a-f]{40}", args.expected_source_sha):
        print("ROLLBACK_RESULT=FAIL")
        return 2
    simulator = args.simulator_root.resolve() if args.simulator_root else None
    if simulator is not None:
        marker = simulator / ".kpv-disposable-simulator"
        if not str(simulator).startswith("/tmp/kpv-simulator-") or not marker.is_file() or marker.is_symlink():
            print("ROLLBACK_RESULT=FAIL")
            return 2
    try:
        installation_path = mapped(simulator, "/etc/codestra/klyrow-production-validator/installation.json")
        if installation_path.is_symlink() or not installation_path.is_file():
            raise ValueError("installation evidence missing")
        installation = json.loads(installation_path.read_text(encoding="utf-8"))
        if installation.get("source_sha") != args.expected_source_sha:
            raise ValueError("source SHA mismatch")
        backup = Path(str(installation["backup_directory"]))
        state = mapped(simulator, "/var/lib/codestra/klyrow-production-validator/install-backups")
        if backup.parent != state or backup.is_symlink() or not backup.is_dir():
            raise ValueError("backup directory rejected")
        records = installation.get("backups")
        if not isinstance(records, list):
            raise ValueError("rollback manifest rejected")
        restore_backups(records, backup)
        version = mapped(simulator, f"/opt/codestra/operators/klyrow-production-validator/{args.expected_source_sha}")
        if version.is_symlink():
            raise ValueError("version path rejected")
        if version.is_dir():
            shutil.rmtree(version)
        print("ROLLBACK_RESULT=PASS")
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        print("ROLLBACK_RESULT=FAIL")
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
