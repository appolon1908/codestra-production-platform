#!/usr/bin/env python3
"""Run candidate authentication in a disposable container before issuer replacement."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "codestra-middleware-webphone-session-issuer-1"
SERVICE = "middleware-webphone-session-issuer"
CHANGED_ENV = {"PROVISIONING_SERVICE_CLIENT_ID", "PROVISIONING_SERVICE_CLIENT_SECRET_FILE"}


def validate_models(before, after, running):
    if set(before["services"]) != set(after["services"]):
        raise ValueError("service_set_changed")
    for name in before["services"]:
        if name != SERVICE and before["services"][name] != after["services"][name]:
            raise ValueError("unrelated_service_changed")
    if {k: v for k, v in before.items() if k != "services"} != {
            k: v for k, v in after.items() if k != "services"}:
        raise ValueError("project_resources_changed")
    old, new = before["services"][SERVICE], after["services"][SERVICE]
    if {k: v for k, v in old.items() if k not in {"environment", "volumes"}} != {
            k: v for k, v in new.items() if k not in {"environment", "volumes"}}:
        raise ValueError("unexpected_service_change")
    changed = {k for k in set(old["environment"]) | set(new["environment"])
               if old["environment"].get(k) != new["environment"].get(k)}
    if not changed <= CHANGED_ENV:
        raise ValueError("unexpected_environment_change")
    if (new["environment"].get("PROVISIONING_SERVICE_CLIENT_ID")
            != "codestra-provisioning-service"
            or new["environment"].get("PROVISIONING_SERVICE_CLIENT_SECRET_FILE")
            != "/run/secrets/provisioning/production-client-secret"):
        raise ValueError("candidate_identity_mismatch")
    image = new.get("image", "")
    if not re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("immutable_image_required")
    if image != running["Config"]["Image"]:
        raise ValueError("running_image_mismatch")
    actual_env = dict(item.split("=", 1) for item in running["Config"]["Env"] if "=" in item)
    if any(actual_env.get(k) != str(v) for k, v in old["environment"].items()):
        raise ValueError("base_environment_drift")
    old_mounts = old.get("volumes", [])
    new_mounts = new.get("volumes", [])
    target = "/run/secrets/provisioning/production-client-secret"
    candidate = [v for v in new_mounts if v.get("target") == target]
    if len(candidate) != 1:
        raise ValueError("candidate_mount_missing")
    volume = candidate[0]
    if (volume.get("type") != "bind" or volume.get("read_only") is not True
            or volume.get("source") !=
            "/etc/codestra/secrets/codestra-compose/provisioning/production-client-secret"
            or volume.get("bind", {}).get("create_host_path") is not False):
        raise ValueError("candidate_mount_contract")
    if [v for v in new_mounts if v.get("target") != target] != [
            v for v in old_mounts if v.get("target") != target]:
        raise ValueError("unrelated_mount_changed")
    return new


def run():
    running = json.loads(subprocess.check_output(["docker", "inspect", CONTAINER]))[0]
    labels = running["Config"]["Labels"]
    if labels["com.docker.compose.project"] != "codestra":
        raise ValueError("unexpected_project")
    cwd = labels["com.docker.compose.project.working_dir"]
    files = labels["com.docker.compose.project.config_files"].split(",")
    base = ["docker", "compose", "--project-name", "codestra"]
    for path in files:
        if not Path(path).is_absolute() or not Path(path).is_file():
            raise ValueError("compose_file_unavailable")
        base += ["-f", path]
    candidate = base + ["-f", str(ROOT / "deploy/webphone/compose.production-auth.yaml")]

    def model(command):
        result = subprocess.run(command + ["config", "--format", "json"], cwd=cwd,
                                capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)

    new = validate_models(model(base), model(candidate), running)
    credential = Path(next(v["source"] for v in new["volumes"]
                           if v["target"] == "/run/secrets/provisioning/production-client-secret"))
    if not credential.is_file():
        raise ValueError("candidate_credential_missing")
    source = (ROOT / "scripts/webphone_auth_preflight.py").read_text()
    result = subprocess.run(
        candidate + ["run", "--rm", "--no-deps", "-T", "--pull", "never",
                     "--entrypoint", "python", SERVICE, "-"],
        cwd=cwd, input=source, capture_output=True, text=True, timeout=150)
    # Docker diagnostics may include interpolated values. Emit only the structured
    # preflight output, never Compose configuration or Docker stderr.
    lines = result.stdout.strip().splitlines()
    report = json.loads(lines[-1]) if lines else {
        "status": "blocked", "reason": "candidate_container_failed"}
    if not isinstance(report, dict) or report.get("status") not in {"pass", "blocked"}:
        raise ValueError("candidate_report_invalid")
    report["running_issuer_replaced"] = False
    print(json.dumps(report, sort_keys=True))
    return result.returncode if result.returncode else (0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "candidate_preflight_unavailable",
                          "running_issuer_replaced": False}))
        raise SystemExit(1)
