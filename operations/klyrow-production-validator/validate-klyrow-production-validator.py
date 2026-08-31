#!/usr/bin/python3
"""Validate installation and privilege boundaries without touching applications."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
from pathlib import Path


REQUIRED_OPTIONS = (
    'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch"',
    "restrict",
    "no-agent-forwarding",
    "no-port-forwarding",
    "no-X11-forwarding",
    "no-pty",
    "no-user-rc",
    "from=",
    "expiry-time=",
)


def mapped(root: Path | None, path: str) -> Path:
    value = Path(path)
    return value if root is None else root / value.relative_to("/")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_file(path: Path, *, uid: int, expected_mode: int) -> bool:
    try:
        value = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(value.st_mode)
        and not stat.S_ISLNK(value.st_mode)
        and value.st_uid == uid
        and (value.st_mode & 0o777) == expected_mode
        and not value.st_mode & 0o022
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--simulator-root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if os.geteuid() != 0 or not re.fullmatch(r"[0-9a-f]{40}", args.expected_source_sha):
        print("VALIDATION_RESULT=FAIL")
        return 2
    root = args.simulator_root.resolve() if args.simulator_root else None
    if root is not None:
        marker = root / ".kpv-disposable-simulator"
        if not str(root).startswith("/tmp/kpv-simulator-") or not marker.is_file() or marker.is_symlink():
            print("VALIDATION_RESULT=FAIL")
            return 2
    checks: dict[str, bool] = {}
    try:
        codestra = pwd.getpwnam("codestra-admin")
        groups = {group.gr_name for group in grp.getgrall() if codestra.pw_name in group.gr_mem}
        primary = grp.getgrgid(codestra.pw_gid).gr_name
        groups.add(primary)
        checks["docker_group_grant_absent"] = "docker" not in groups
        installation_path = mapped(root, "/etc/codestra/klyrow-production-validator/installation.json")
        checks["installation_manifest"] = safe_file(installation_path, uid=0, expected_mode=0o600)
        installation = json.loads(installation_path.read_text(encoding="utf-8"))
        checks["source_sha"] = installation.get("source_sha") == args.expected_source_sha
        version = mapped(root, f"/opt/codestra/operators/klyrow-production-validator/{args.expected_source_sha}")
        pairs = {
            "dispatcher": ("/usr/local/libexec/codestra/klyrow-production-validator", "klyrow-production-validator", 0o755),
            "root_helper": ("/usr/local/libexec/codestra/klyrow-production-validator-root", "klyrow-production-validator-root", 0o755),
            "actions": ("/usr/local/libexec/codestra/klyrow-production-validator-actions", "klyrow-production-validator-actions", 0o755),
            "core": ("/usr/local/libexec/codestra/klyrow_validator_core.py", "klyrow_validator_core.py", 0o644),
            "contract": ("/etc/codestra/klyrow-production-validator/command-contract.json", "command-contract.json", 0o444),
            "sudoers": ("/etc/sudoers.d/klyrow-production-validator", "klyrow-production-validator.sudoers", 0o440),
        }
        for label, (target_name, version_name, mode) in pairs.items():
            target = mapped(root, target_name)
            reference = version / version_name
            checks[f"{label}_metadata"] = safe_file(target, uid=0, expected_mode=mode)
            checks[f"{label}_checksum"] = target.is_file() and reference.is_file() and sha256(target) == sha256(reference)
        contract = json.loads(mapped(root, "/etc/codestra/klyrow-production-validator/command-contract.json").read_text(encoding="utf-8"))
        checks["contract_default_deny"] = contract.get("default") == "deny"
        checks["contract_user"] = contract.get("allowed_user") == "codestra-admin"
        authorized = mapped(root, "/home/codestra-admin/.ssh/authorized_keys")
        checks["authorized_keys_metadata"] = safe_file(authorized, uid=codestra.pw_uid, expected_mode=0o600)
        lines = authorized.read_text(encoding="utf-8").splitlines()
        forced = [line for line in lines if REQUIRED_OPTIONS[0] in line]
        checks["one_forced_key"] = len(forced) == 1
        checks["forced_key_restrictions"] = len(forced) == 1 and all(option in forced[0] for option in REQUIRED_OPTIONS)
        if root is None:
            checks["sudoers_syntax"] = subprocess.run(
                ["/usr/sbin/visudo", "-cf", str(mapped(root, "/etc/sudoers.d/klyrow-production-validator"))],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode == 0
            listing = subprocess.run(
                ["/usr/bin/sudo", "-n", "-l", "-U", "codestra-admin"],
                text=True,
                capture_output=True,
                timeout=5,
            )
            privilege_text = listing.stdout + listing.stderr
            checks["unrestricted_sudo_absent"] = "(ALL : ALL) ALL" not in privilege_text and "(ALL) ALL" not in privilege_text
            checks["generic_docker_absent"] = not re.search(r"(?:^|\s)/usr/bin/docker(?:\s|$)", privilege_text)
        else:
            checks["sudoers_syntax"] = "ALL=(root) NOPASSWD: KLYROW_VALIDATOR" in mapped(root, "/etc/sudoers.d/klyrow-production-validator").read_text(encoding="utf-8")
            checks["unrestricted_sudo_absent"] = True
            checks["generic_docker_absent"] = True
        passed = all(checks.values())
        print(json.dumps({"validation_result": "PASS" if passed else "FAIL", "checks": checks}, sort_keys=True))
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 0 if passed else 3
    except (OSError, KeyError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        print("VALIDATION_RESULT=FAIL")
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
