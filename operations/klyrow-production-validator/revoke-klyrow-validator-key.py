#!/usr/bin/python3
"""Revoke only the validator key, leaving unrelated operator keys intact."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

from install_klyrow_production_validator_compat import (
    InstallError,
    atomic_replace_text,
    read_private_text,
)


FORCED = 'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch"'


def fingerprint(key_type: str, key_blob: str) -> str | None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", delete=True) as handle:
        handle.write(f"{key_type} {key_blob}\n")
        handle.flush()
        result = subprocess.run(["/usr/bin/ssh-keygen", "-lf", handle.name], text=True, capture_output=True)
    return result.stdout.split()[1] if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-fingerprint", required=True)
    parser.add_argument("--simulator-root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{20,60}", args.expected_fingerprint):
        print("REVOCATION_RESULT=FAIL")
        return 2
    root = args.simulator_root.resolve() if args.simulator_root else None
    if root is not None:
        marker = root / ".kpv-disposable-simulator"
        if not str(root).startswith("/tmp/kpv-simulator-") or not marker.is_file() or marker.is_symlink():
            print("REVOCATION_RESULT=FAIL")
            return 2
    elif os.geteuid() != 0:
        print("REVOCATION_RESULT=FAIL")
        return 2
    target = Path("/home/codestra-admin/.ssh/authorized_keys") if root is None else root / "home/codestra-admin/.ssh/authorized_keys"
    try:
        text, metadata = read_private_text(target)
        retained: list[str] = []
        removed = 0
        for line in text.splitlines():
            fields = line.split()
            matched = False
            if FORCED in line:
                for index, value in enumerate(fields[:-1]):
                    if value == "ssh-ed25519" and fingerprint(value, fields[index + 1]) == args.expected_fingerprint:
                        matched = True
                        break
            if matched:
                removed += 1
            else:
                retained.append(line)
        if removed != 1:
            raise ValueError("expected exactly one key")
        atomic_replace_text(
            target,
            "\n".join(retained) + ("\n" if retained else ""),
            metadata,
            label="revoke",
        )
        print("REVOCATION_RESULT=PASS")
        print("UNRELATED_KEYS_CHANGED=NO")
        return 0
    except (InstallError, OSError, ValueError):
        print("REVOCATION_RESULT=FAIL")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
