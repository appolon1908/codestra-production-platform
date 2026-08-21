#!/usr/bin/python3
"""Root-side, allowlisted Codestra production operator.

This program accepts one fixed command shape and never evaluates shell text.
It is suitable for an OpenSSH forced-command entry combined with a single
sudoers rule. Every operation remains fail closed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

CONFIG = Path("/etc/codestra/production-operator/release.json")
LOCK = Path("/run/lock/codestra-production-operator.lock")
AUDIT = Path("/var/log/codestra/production-operator.jsonl")
EVIDENCE = Path("/var/lib/codestra/production-operator/evidence")
CONTAINER = "codestra-production-standby-approved"
IMAGE = "ghcr.io/codestra-srl/codestra-middleware"
ALLOWED = {
    "preflight", "backup", "validate-backup", "restore-test", "stage",
    "canary", "status", "rollback", "collect-evidence",
}
STATE_CHANGING = {"backup", "restore-test", "stage", "canary", "rollback"}
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
CHANGE_RE = re.compile(r"CHG-[0-9]{8}-CODESTRA-PRODUCTION-ACTIVATION-[0-9]{2}")
DATE_RE = re.compile(r"20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])")
FIXED_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}


class Denied(RuntimeError):
    pass


def load_config() -> dict[str, str]:
    if CONFIG.is_symlink() or not CONFIG.is_file():
        raise Denied("operator release configuration is unavailable")
    st = CONFIG.stat()
    if st.st_uid != 0 or st.st_mode & 0o022:
        raise Denied("operator release configuration permissions are unsafe")
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    required = {"protected_sha", "image_digest", "change_id", "maintenance_date"}
    if set(data) != required:
        raise Denied("operator release configuration schema mismatch")
    return data


def parse(argv: list[str]) -> tuple[str, str, str, str, str]:
    if argv == ["forced"]:
        original = os.environ.get("SSH_ORIGINAL_COMMAND", "")
        # A deliberately tiny grammar: five ASCII tokens and no quoting.
        if not original or any(c.isspace() and c != " " for c in original):
            raise Denied("invalid forced command")
        argv = original.split(" ")
        if any(not part for part in argv):
            raise Denied("invalid forced command spacing")
    if len(argv) != 5:
        raise Denied("expected: ACTION SHA DIGEST CHANGE_ID MAINTENANCE_DATE")
    action, sha, digest, change_id, maintenance_date = argv
    if action not in ALLOWED:
        raise Denied("action is not allowlisted")
    if not SHA_RE.fullmatch(sha) or not DIGEST_RE.fullmatch(digest):
        raise Denied("release identifier format rejected")
    if not CHANGE_RE.fullmatch(change_id) or not DATE_RE.fullmatch(maintenance_date):
        raise Denied("change identifier or maintenance date rejected")
    return action, sha, digest, change_id, maintenance_date


def bind(request: tuple[str, str, str, str, str], config: dict[str, str]) -> None:
    _, sha, digest, change_id, maintenance_date = request
    expected = (config["protected_sha"], config["image_digest"], config["change_id"], config["maintenance_date"])
    if (sha, digest, change_id, maintenance_date) != expected:
        raise Denied("request does not match installed immutable release tuple")


def require_window(action: str, maintenance_date: str) -> None:
    if action not in STATE_CHANGING:
        return
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.date().isoformat() != maintenance_date or not (time(0, 0) <= now.time() < time(4, 0)):
        raise Denied("state-changing action is outside the approved maintenance window")


def run(args: list[str], *, stdin: bytes | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args, input=stdin, env=FIXED_ENV, check=True, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def docker_inspect(container: str) -> dict:
    result = run(["/usr/bin/docker", "inspect", container], timeout=30)
    return json.loads(result.stdout)[0]


def fail_closed_values() -> dict[str, str]:
    return {
        "PSTN_DIALING": "DISABLED",
        "PRODUCTION_DIALING": "DISABLED",
        "SEND_EVENTS": "false",
        "ENABLE_EXTERNAL_DELIVERY": "false",
        "LIVE_WRITE": "false",
        "ODOO_WRITE": "false",
        "N8N_DELIVERY_ENABLED": "false",
        "CALLS_PLACED": "0",
    }


def status(config: dict[str, str]) -> dict:
    result: dict[str, object] = {"release": config, "safety": fail_closed_values()}
    try:
        obj = docker_inspect(CONTAINER)
        result["standby"] = {
            "exists": True,
            "running": obj["State"]["Running"],
            "image": obj["Image"],
            "network_mode": obj["HostConfig"]["NetworkMode"],
        }
    except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError):
        result["standby"] = {"exists": False}
    return result


def preflight(config: dict[str, str]) -> dict:
    usage = shutil.disk_usage("/")
    free_percent = int(usage.free * 100 / usage.total)
    if free_percent < 15:
        raise Denied("disk headroom below 15 percent")
    run(["/usr/bin/docker", "info", "--format", "{{.ServerVersion}}"], timeout=30)
    return {"result": "PASS", "disk_free_percent": free_percent, "safety": fail_closed_values()}


def fixed_script(path: str) -> dict:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise Denied(f"trusted action is unavailable: {candidate.name}")
    st = candidate.stat()
    if st.st_uid != 0 or st.st_mode & 0o022:
        raise Denied(f"trusted action permissions are unsafe: {candidate.name}")
    result = run([path], timeout=7200)
    return {"result": "PASS", "output_sha256": hashlib.sha256(result.stdout).hexdigest()}


def stage(config: dict[str, str]) -> dict:
    credential_bytes = sys.stdin.buffer.read(16384)
    if (not credential_bytes or len(credential_bytes) >= 16384 or
            b"\x00" in credential_bytes or b"\n" in credential_bytes or
            b"\r" in credential_bytes):
        raise Denied("invalid GHCR credential input")
    subject = f"{IMAGE}@{config['image_digest']}"
    docker_config = Path(tempfile.mkdtemp(prefix="codestra-docker-", dir="/run"))
    try:
        run([
            "/usr/bin/docker", "--config", str(docker_config), "login", "ghcr.io",
            "--username", "appolon1908-hue", "--password-stdin",
        ], stdin=credential_bytes, timeout=60)
        credential_bytes = b""
        run(["/usr/bin/docker", "--config", str(docker_config), "pull", "--quiet", subject], timeout=1800)
        inspected = run(["/usr/bin/docker", "image", "inspect", subject], timeout=60)
        image = json.loads(inspected.stdout)[0]
        if not any(item == subject for item in image.get("RepoDigests", [])):
            raise Denied("pulled image RepoDigest does not match the installed release tuple")
    finally:
        credential_bytes = b""
        shutil.rmtree(docker_config, ignore_errors=True)
    try:
        old = docker_inspect(CONTAINER)
        if old["Config"]["Image"] != subject:
            raise Denied("fixed standby container exists with a different digest")
        run(["/usr/bin/docker", "start", CONTAINER], timeout=60)
    except subprocess.CalledProcessError:
        run([
            "/usr/bin/docker", "create", "--name", CONTAINER,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--env", "PSTN_DIALING=DISABLED", "--env", "PRODUCTION_DIALING=DISABLED",
            "--env", "SEND_EVENTS=false", "--env", "ENABLE_EXTERNAL_DELIVERY=false",
            "--env", "LIVE_WRITE=false", "--env", "ODOO_WRITE=false",
            "--env", "N8N_DELIVERY_ENABLED=false", subject,
        ], timeout=120)
        run(["/usr/bin/docker", "start", CONTAINER], timeout=60)
    obj = docker_inspect(CONTAINER)
    if obj["Config"]["Image"] != subject or obj["HostConfig"]["NetworkMode"] != "none":
        raise Denied("standby digest or isolation read-back failed")
    return {"result": "PASS", "subject": subject, "network_mode": "none", "safety": fail_closed_values()}


def canary(config: dict[str, str]) -> dict:
    obj = docker_inspect(CONTAINER)
    subject = f"{IMAGE}@{config['image_digest']}"
    if obj["Config"]["Image"] != subject or obj["HostConfig"]["NetworkMode"] != "none":
        raise Denied("standby certification mismatch")
    if not obj["State"]["Running"]:
        raise Denied("standby is not running")
    return {"result": "PASS", "external_side_effects": 0, "network_mode": "none"}


def rollback(config: dict[str, str]) -> dict:
    try:
        obj = docker_inspect(CONTAINER)
    except subprocess.CalledProcessError:
        return {"result": "PASS", "candidate_present": False}
    subject = f"{IMAGE}@{config['image_digest']}"
    if obj["Config"]["Image"] != subject:
        raise Denied("refusing to remove a container outside the installed release tuple")
    run(["/usr/bin/docker", "stop", "--time", "20", CONTAINER], timeout=60)
    run(["/usr/bin/docker", "rm", CONTAINER], timeout=60)
    return {"result": "PASS", "candidate_present": False, "data_loss": 0}


def dispatch(action: str, config: dict[str, str]) -> dict:
    if action == "preflight":
        return preflight(config)
    if action == "status":
        return status(config)
    if action == "backup":
        return fixed_script("/opt/codestra/operations/backup/codestra-backup.sh")
    if action == "validate-backup":
        return fixed_script("/opt/codestra/operations/backup/check-backup-state.sh")
    if action == "restore-test":
        return fixed_script("/opt/codestra/restore-validation/verify_restore_and_hmac.sh")
    if action == "stage":
        return stage(config)
    if action == "canary":
        return canary(config)
    if action == "rollback":
        return rollback(config)
    if action == "collect-evidence":
        return {"result": "PASS", "status": status(config)}
    raise Denied("unreachable action")


def audit(action: str, outcome: str, detail: str = "") -> None:
    record = {
        "timestamp": datetime.now(ZoneInfo("UTC")).isoformat(),
        "action": action,
        "outcome": outcome,
        "detail": detail[:240],
    }
    with AUDIT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def main() -> int:
    action = "invalid"
    LOCK.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with LOCK.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("OPERATOR_RESULT=DENIED\nREASON=concurrent operation", file=sys.stderr)
            return 75
        try:
            request = parse(sys.argv[1:])
            action = request[0]
            config = load_config()
            bind(request, config)
            require_window(action, request[4])
            result = dispatch(action, config)
            audit(action, "PASS")
            print(json.dumps(result, sort_keys=True))
            return 0
        except (Denied, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            audit(action, "FAIL", str(exc))
            print("OPERATOR_RESULT=FAIL", file=sys.stderr)
            print(f"REASON={str(exc)[:240]}", file=sys.stderr)
            return 77


if __name__ == "__main__":
    raise SystemExit(main())
