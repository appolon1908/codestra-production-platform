#!/usr/bin/env python3
"""Fail-closed reconciliation for the governed Server A architecture overrides."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_ROOT = ROOT / "deploy/architecture-remediation"
NETWORKS = ("codestra-provider-email", "codestra-provider-sms", "codestra-provider-voice")
NETWORK_LABELS = {
    "codestra.governance": "runtime-architecture-remediation.v1",
    "codestra.scope": "private-provider-connector",
}


@dataclass(frozen=True)
class Project:
    name: str
    anchor: str
    services: tuple[str, ...]
    override: str
    env_file: str | None = None
    image_environment: tuple[tuple[str, str], ...] = ()


PROJECTS = (
    Project("codestra", "codestra-middleware-1", ("postgres", "middleware"), "compose.core-provider-networks.yaml"),
    Project("codestra-beyvra-email", "codestra-beyvra-email-api-1", ("api",), "compose.beyvra-email.yaml", image_environment=(("BEYVRA_EMAIL_IMAGE", "codestra-beyvra-email-api-1"),)),
    Project("codestra-email-reseller", "codestra-email-reseller-api-1", ("api",), "compose.email-reseller.yaml"),
    Project("codestra-integration-control-plane", "codestra-integration-control-plane-api-1", ("api", "worker"), "compose.endpoint-overrides.yaml"),
    Project("private-integration", "private-integration-gateway-1", ("gateway",), "compose.private-integration.yaml"),
    Project("codestra-sms-api", "codestra-sms-api-api-1", ("api", "event-worker"), "compose.sms-api.yaml", env_file="/opt/codestra/sms-api/.env"),
    Project("codestra-websocket-gateway", "codestra-websocket-gateway-gateway-1", ("gateway",), "compose.websocket-gateway.yaml", image_environment=(("GATEWAY_IMAGE", "codestra-websocket-gateway-gateway-1"), ("GATEWAY_DIGEST", "codestra-websocket-gateway-gateway-1"))),
)


class ReconcileError(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900, check=False)
    if result.returncode:
        raise ReconcileError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}")
    return result


def inspect_container(name: str) -> dict:
    result = run(["/usr/bin/docker", "inspect", name])
    payload = json.loads(result.stdout)
    if len(payload) != 1:
        raise ReconcileError(f"unexpected inspect result for {name}")
    return payload[0]


def checked_regular(path: Path, *, secret: bool = False, anchored_source: bool = False) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ReconcileError(f"unsafe governed file: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if not anchored_source and (info.st_uid != 0 or info.st_gid != 0):
        raise ReconcileError(f"unsafe governed ownership: {path}")
    if anchored_source and mode & 0o002:
        raise ReconcileError(f"anchored Compose source is world-writable: {path}")
    if secret and mode & 0o077:
        raise ReconcileError(f"secret environment file is too permissive: {path}")
    if not secret and not anchored_source and mode & 0o022:
        raise ReconcileError(f"governed file is writable by group/other: {path}")


def image_value(container: dict, variable: str) -> str:
    image = container["Config"]["Image"]
    if "@sha256:" not in image:
        inspected = json.loads(run(["/usr/bin/docker", "image", "inspect", image]).stdout)[0]
        digests = inspected.get("RepoDigests") or []
        if len(digests) != 1 or "@sha256:" not in digests[0]:
            raise ReconcileError(f"{container['Name']} has no unique immutable image digest")
        image = digests[0]
    if variable.endswith("_DIGEST"):
        return image.rsplit("@", 1)[1]
    if variable == "GATEWAY_IMAGE":
        return image.rsplit("@", 1)[0]
    return image


def project_command(project: Project) -> tuple[list[str], Path, dict[str, str]]:
    anchor = inspect_container(project.anchor)
    labels = anchor.get("Config", {}).get("Labels", {})
    if labels.get("com.docker.compose.project") != project.name:
        raise ReconcileError(f"project mismatch for {project.anchor}")
    workdir = Path(labels.get("com.docker.compose.project.working_dir", ""))
    config_files = labels.get("com.docker.compose.project.config_files", "").split(",")
    if not workdir.is_absolute() or not config_files or any(not Path(item).is_absolute() for item in config_files):
        raise ReconcileError(f"invalid Compose source labels for {project.name}")
    for item in config_files:
        # These paths are accepted only because Docker's immutable container
        # metadata anchors them to the exact running Compose project.
        checked_regular(Path(item), anchored_source=True)
    override = OVERRIDE_ROOT / project.override
    checked_regular(override)
    command = ["/usr/bin/docker", "compose", "--project-name", project.name]
    if project.env_file:
        checked_regular(Path(project.env_file), secret=True)
        command.extend(["--env-file", project.env_file])
    for item in config_files:
        command.extend(["--file", item])
    command.extend(["--file", str(override)])
    environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
    for variable, container_name in project.image_environment:
        environment[variable] = image_value(inspect_container(container_name), variable)
    return command, workdir, environment


def preflight() -> list[tuple[Project, list[str], Path, dict[str, str]]]:
    if os.geteuid() != 0:
        raise ReconcileError("root is required")
    prepared = []
    for project in PROJECTS:
        command, workdir, environment = project_command(project)
        run([*command, "config", "--quiet"], cwd=workdir, env=environment)
        prepared.append((project, command, workdir, environment))
    return prepared


def ensure_network(name: str) -> str:
    result = subprocess.run(["/usr/bin/docker", "network", "inspect", name], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if result.returncode == 0:
        network = json.loads(result.stdout)[0]
        labels = network.get("Labels") or {}
        if any(labels.get(key) != value for key, value in NETWORK_LABELS.items()):
            raise ReconcileError(f"existing network is not governed: {name}")
        return "present"
    command = ["/usr/bin/docker", "network", "create", "--driver", "bridge", "--internal"]
    for key, value in NETWORK_LABELS.items():
        command.extend(["--label", f"{key}={value}"])
    command.append(name)
    run(command)
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="reconcile the preflighted fixed projects")
    args = parser.parse_args()
    try:
        prepared = preflight()
        result: dict[str, object] = {"preflight": "PASS", "apply": "NOT_REQUESTED", "networks": {}, "projects": {}}
        if args.apply:
            result["networks"] = {name: ensure_network(name) for name in NETWORKS}
            for project, command, workdir, environment in prepared:
                run([*command, "up", "--detach", "--no-deps", *project.services], cwd=workdir, env=environment)
                result["projects"][project.name] = "RECONCILED"
            result["apply"] = "PASS"
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, ReconcileError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
