#!/usr/bin/python3
"""Validate installation and privilege boundaries without touching applications."""

from __future__ import annotations

import argparse
import base64
import grp
import hashlib
import ipaddress
import json
import os
import pwd
import re
import stat
import subprocess
from datetime import datetime, timezone
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
FORCED_KEY_RE = re.compile(
    r'\Afrom="(?P<source>[^"\r\n]+)",'
    r'expiry-time="(?P<expiry>20[0-9]{12}Z)",'
    r'command="/usr/local/libexec/codestra/klyrow-production-validator ssh-dispatch",'
    r'restrict,no-agent-forwarding,no-port-forwarding,no-X11-forwarding,no-pty,no-user-rc '
    r'(?P<key_type>ssh-ed25519) (?P<key_blob>[A-Za-z0-9+/]+={0,3})\Z'
)
UNRESTRICTED_COMMAND_RE = re.compile(
    r"\)\s+(?:(?:NO)?(?:PASSWD|SETENV|EXEC|LOG_INPUT|LOG_OUTPUT|MAIL|FOLLOW):\s*)*"
    r"ALL(?:\s|,|$)",
    re.MULTILINE,
)
FORBIDDEN_PRIVILEGED_EXECUTABLE_RE = re.compile(
    r"(?:^|[\s,])/(?:usr/)?(?:local/)?(?:s?bin/)?(?:docker|podman|systemctl|bash|sh|"
    r"dash|zsh|fish|python[0-9.]*|perl|ruby|node|vi|vim|nano|less|more)"
    r"(?:\s|,|$)",
    re.MULTILINE,
)
ROOT_HELPER = "/usr/local/libexec/codestra/klyrow-production-validator-root"
APPROVED_SUDO_ACTIONS = (
    "authenticate-runbook",
    "inventory",
    "configuration-readback",
    "release-identity",
    "health",
    "authorization-tests",
    "no-effect-tests",
    "callback-tests",
    "smtp-no-data",
    "collect-evidence",
    "status",
)
APPROVED_SUDO_COMMAND_RE = re.compile(
    re.escape(ROOT_HELPER)
    + r" (?P<action>"
    + "|".join(APPROVED_SUDO_ACTIONS)
    + r")(?=\s*(?:,|\Z))"
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


def safe_reference(path: Path, *, uid: int) -> bool:
    try:
        value = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(value.st_mode)
        and not stat.S_ISLNK(value.st_mode)
        and value.st_uid == uid
        and not value.st_mode & 0o022
    )


def forced_key_details(line: str) -> dict[str, str] | None:
    match = FORCED_KEY_RE.fullmatch(line)
    if match is None:
        return None
    try:
        decoded = base64.b64decode(match.group("key_blob"), validate=True)
        network = ipaddress.ip_network(match.group("source"), strict=False)
        expiry = datetime.strptime(match.group("expiry"), "%Y%m%d%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return None
    minimum_prefix = 24 if network.version == 4 else 64
    if network.prefixlen < minimum_prefix or expiry <= datetime.now(timezone.utc):
        return None
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(decoded).digest()).decode(
        "ascii"
    ).rstrip("=")
    return {
        "source_restriction": match.group("source"),
        "expires_at": match.group("expiry"),
        "key_fingerprint": fingerprint,
    }


def sudo_listing_is_bounded(returncode: int, value: str) -> bool:
    if (
        returncode != 0
        or "may run the following commands" not in value
        or UNRESTRICTED_COMMAND_RE.search(value) is not None
        or FORBIDDEN_PRIVILEGED_EXECUTABLE_RE.search(value) is not None
    ):
        return False
    grants = " ".join(value.split("may run the following commands", 1)[1].split())
    matches = list(APPROVED_SUDO_COMMAND_RE.finditer(grants))
    if len(matches) != len(APPROVED_SUDO_ACTIONS) or {
        match.group("action") for match in matches
    } != set(APPROVED_SUDO_ACTIONS):
        return False
    residual = APPROVED_SUDO_COMMAND_RE.sub("", grants)
    return "/" not in residual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--simulator-root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_source_sha):
        print("VALIDATION_RESULT=FAIL")
        return 2
    root = args.simulator_root.resolve() if args.simulator_root else None
    if root is not None:
        marker = root / ".kpv-disposable-simulator"
        if not str(root).startswith("/tmp/kpv-simulator-") or not marker.is_file() or marker.is_symlink():
            print("VALIDATION_RESULT=FAIL")
            return 2
    elif os.geteuid() != 0:
        print("VALIDATION_RESULT=FAIL")
        return 2
    install_uid = os.geteuid() if root is not None else 0
    checks: dict[str, bool] = {}
    try:
        codestra = pwd.getpwuid(os.geteuid()) if root is not None else pwd.getpwnam("codestra-admin")
        if root is None:
            groups = {group.gr_name for group in grp.getgrall() if codestra.pw_name in group.gr_mem}
            primary = grp.getgrgid(codestra.pw_gid).gr_name
            groups.add(primary)
            checks["docker_group_grant_absent"] = "docker" not in groups
        else:
            checks["docker_group_grant_absent"] = True
        installation_path = mapped(root, "/etc/codestra/klyrow-production-validator/installation.json")
        checks["installation_manifest"] = safe_file(installation_path, uid=install_uid, expected_mode=0o600)
        if not checks["installation_manifest"]:
            raise ValueError("installation metadata rejected")
        installation = json.loads(installation_path.read_text(encoding="utf-8"))
        if not isinstance(installation, dict):
            raise ValueError("installation schema rejected")
        checks["source_sha"] = installation.get("source_sha") == args.expected_source_sha
        identity_path = mapped(root, "/etc/codestra/klyrow-production-validator/operator-identity.json")
        checks["identity_metadata"] = safe_file(
            identity_path, uid=install_uid, expected_mode=0o444
        )
        if not checks["identity_metadata"]:
            raise ValueError("identity metadata rejected")
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        if not isinstance(identity, dict):
            raise ValueError("identity schema rejected")
        identity_fields = {
            "key_fingerprint",
            "source_restriction",
            "expires_at",
            "owner",
            "approver",
        }
        checks["identity_schema"] = set(identity) == identity_fields
        checks["identity_owner"] = identity.get("owner") == "codestra-admin"
        checks["identity_installation_binding"] = all(
            identity.get(field) == installation.get(field)
            for field in ("key_fingerprint", "source_restriction", "expires_at", "approver")
        )
        version = mapped(root, f"/opt/codestra/operators/klyrow-production-validator/{args.expected_source_sha}")
        release_evidence = {
            "release_manifest": (
                "release-installation-manifest.json",
                "release_manifest_sha256",
            ),
            "sbom": ("release-sbom.spdx.json", "sbom_sha256"),
            "provenance": ("release-provenance.json", "provenance_sha256"),
            "vulnerability_report": (
                "release-vulnerability-report.json",
                "vulnerability_report_sha256",
            ),
            "checksum_manifest": ("release-SHA256SUMS", "checksum_manifest_sha256"),
            "signature": ("release-SHA256SUMS.sig", "signature_sha256"),
            "allowed_signers": ("release-allowed-signers", "allowed_signers_sha256"),
        }
        release_paths: dict[str, Path] = {}
        for label, (filename, installation_field) in release_evidence.items():
            path = version / filename
            release_paths[label] = path
            checks[f"{label}_metadata"] = safe_reference(path, uid=install_uid)
            expected_digest = installation.get(installation_field)
            checks[f"{label}_checksum"] = (
                checks[f"{label}_metadata"]
                and isinstance(expected_digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", expected_digest) is not None
                and sha256(path) == expected_digest
            )
        if not all(
            checks[f"{label}_metadata"] and checks[f"{label}_checksum"]
            for label in release_evidence
        ):
            raise ValueError("release evidence metadata rejected")
        release_manifest = json.loads(release_paths["release_manifest"].read_text(encoding="utf-8"))
        if not isinstance(release_manifest, dict):
            raise ValueError("release manifest schema rejected")
        checks["release_manifest_binding"] = (
            release_manifest.get("source_sha") == args.expected_source_sha
            and release_manifest.get("artifact_sha256") == installation.get("artifact_sha256")
            and release_manifest.get("application_runtime_mutations") == 0
        )
        signature_check = subprocess.run(
            [
                "/usr/bin/ssh-keygen",
                "-Y",
                "verify",
                "-q",
                "-f",
                str(release_paths["allowed_signers"]),
                "-I",
                "codestra-release",
                "-n",
                "codestra-klyrow-validator",
                "-s",
                str(release_paths["signature"]),
            ],
            input=release_paths["checksum_manifest"].read_bytes(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        checks["release_signature"] = (
            installation.get("release_signature_verification") == "PASS"
            and signature_check.returncode == 0
        )
        pairs = {
            "dispatcher": ("/usr/local/libexec/codestra/klyrow-production-validator", "klyrow-production-validator", 0o755),
            "root_helper": ("/usr/local/libexec/codestra/klyrow-production-validator-root", "klyrow-production-validator-root", 0o755),
            "actions": ("/usr/local/libexec/codestra/klyrow-production-validator-actions", "klyrow-production-validator-actions", 0o755),
            "core": ("/usr/local/libexec/codestra/klyrow_validator_core.py", "klyrow_validator_core.py", 0o644),
            "contract": ("/etc/codestra/klyrow-production-validator/command-contract.json", "command-contract.json", 0o444),
            "sudoers": ("/etc/sudoers.d/klyrow-production-validator", "klyrow-production-validator.sudoers", 0o440),
            "probe_core": ("/opt/codestra/operators/klyrow-production-validator/probes/kpv_probe_core.py", "kpv_probe_core.py", 0o444),
            "probe_authorization": ("/opt/codestra/operators/klyrow-production-validator/probes/authorization-tests", "probe-authorization-tests", 0o555),
            "probe_no_effect": ("/opt/codestra/operators/klyrow-production-validator/probes/no-effect-tests", "probe-no-effect-tests", 0o555),
            "probe_callback": ("/opt/codestra/operators/klyrow-production-validator/probes/callback-tests", "probe-callback-tests", 0o555),
            "probe_smtp": ("/opt/codestra/operators/klyrow-production-validator/probes/smtp-no-data", "probe-smtp-no-data", 0o555),
        }
        for label, (target_name, version_name, mode) in pairs.items():
            target = mapped(root, target_name)
            reference = version / version_name
            checks[f"{label}_metadata"] = safe_file(target, uid=install_uid, expected_mode=mode)
            checks[f"{label}_reference_metadata"] = safe_reference(reference, uid=install_uid)
            checks[f"{label}_checksum"] = (
                checks[f"{label}_metadata"]
                and checks[f"{label}_reference_metadata"]
                and sha256(target) == sha256(reference)
            )
        contract_path = mapped(root, "/etc/codestra/klyrow-production-validator/command-contract.json")
        if not checks["contract_metadata"]:
            raise ValueError("contract metadata rejected")
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if not isinstance(contract, dict):
            raise ValueError("contract schema rejected")
        checks["contract_default_deny"] = contract.get("default") == "deny"
        checks["contract_user"] = contract.get("allowed_user") == "codestra-admin"
        probe_manifest_path = mapped(root, "/etc/codestra/klyrow-production-validator/probe-manifest.json")
        checks["probe_manifest_metadata"] = safe_file(
            probe_manifest_path, uid=install_uid, expected_mode=0o444
        )
        if not checks["probe_manifest_metadata"]:
            raise ValueError("probe manifest metadata rejected")
        probe_manifest = json.loads(probe_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(probe_manifest, dict):
            raise ValueError("probe manifest schema rejected")
        checks["probe_manifest_schema"] = (
            probe_manifest.get("schema_version") == "1.0.0"
            and set(probe_manifest.get("probes", {}))
            == {"authorization-tests", "no-effect-tests", "callback-tests", "smtp-no-data"}
        )
        authorized = mapped(root, "/home/codestra-admin/.ssh/authorized_keys")
        checks["authorized_keys_metadata"] = safe_file(authorized, uid=codestra.pw_uid, expected_mode=0o600)
        if not checks["authorized_keys_metadata"]:
            raise ValueError("authorized keys metadata rejected")
        lines = authorized.read_text(encoding="utf-8").splitlines()
        forced = [line for line in lines if REQUIRED_OPTIONS[0] in line]
        checks["one_forced_key"] = len(forced) == 1
        forced_details = forced_key_details(forced[0]) if len(forced) == 1 else None
        checks["forced_key_restrictions"] = forced_details is not None
        checks["forced_key_identity"] = forced_details is not None and all(
            forced_details.get(field) == identity.get(field)
            for field in ("key_fingerprint", "source_restriction", "expires_at")
        )
        checks["authorized_keys_checksum"] = (
            installation.get("authorized_keys_sha256") == sha256(authorized)
        )
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
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
            privilege_text = listing.stdout + listing.stderr
            checks["sudo_listing_success"] = listing.returncode == 0
            checks["unrestricted_sudo_absent"] = sudo_listing_is_bounded(
                listing.returncode, privilege_text
            )
            checks["generic_docker_absent"] = (
                FORBIDDEN_PRIVILEGED_EXECUTABLE_RE.search(privilege_text) is None
            )
        else:
            checks["sudoers_syntax"] = "ALL=(root) NOPASSWD: KLYROW_VALIDATOR" in mapped(root, "/etc/sudoers.d/klyrow-production-validator").read_text(encoding="utf-8")
            checks["unrestricted_sudo_absent"] = True
            checks["generic_docker_absent"] = True
        passed = all(checks.values())
        print(json.dumps({"validation_result": "PASS" if passed else "FAIL", "checks": checks}, sort_keys=True))
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 0 if passed else 3
    except (
        OSError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ):
        print("VALIDATION_RESULT=FAIL")
        print("APPLICATION_RUNTIME_CHANGED=NO")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
