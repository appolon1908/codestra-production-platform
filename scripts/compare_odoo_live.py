#!/usr/bin/env python3
"""Compare canonical Odoo Compose semantics with the running container."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ODOO = ROOT / "deploy/odoo"
FILES = [line for line in (ODOO / "compose-order.txt").read_text().splitlines() if line]


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True)


compose_args = ["docker", "compose"]
for relative in FILES:
    compose_args += ["-f", str(ODOO / relative)]
desired = json.loads(run(*compose_args, "config", "--format", "json"))
live = json.loads(run("docker", "inspect", "codestra-odoo-1"))[0]
service = desired["services"]["odoo"]

desired_networks = {
    desired["networks"][name].get("name", name) for name in service["networks"]
}
live_networks = set(live["NetworkSettings"]["Networks"])

desired_mounts = set()
for mount in service["volumes"]:
    source = mount["source"]
    if mount["type"] == "volume":
        source = desired["volumes"][source].get("name", source)
    desired_mounts.add(
        (mount["type"], source, mount["target"], bool(mount.get("read_only", False)))
    )
live_mounts = {
    (mount["Type"], mount.get("Name") or mount["Source"], mount["Destination"], not mount["RW"])
    for mount in live["Mounts"]
}

desired_env = {key: str(value) for key, value in service["environment"].items()}
live_env = dict(item.split("=", 1) for item in live["Config"]["Env"] if "=" in item)
live_selected_env = {key: live_env.get(key) for key in desired_env}

checks = {
    "image": (service["image"], live["Config"]["Image"]),
    "entrypoint": (service["entrypoint"], live["Config"]["Entrypoint"]),
    "command": (service["command"], live["Config"]["Cmd"]),
    "environment": (desired_env, live_selected_env),
    "networks": (desired_networks, live_networks),
    "mounts": (desired_mounts, live_mounts),
    "published_ports": ([], live["HostConfig"]["PortBindings"] or []),
    "restart": (service["restart"], live["HostConfig"]["RestartPolicy"]["Name"]),
    "memory": (int(service["mem_limit"]), live["HostConfig"]["Memory"]),
    "cpus": (int(float(service["cpus"]) * 1_000_000_000), live["HostConfig"]["NanoCpus"]),
}

drift = []
for name, (expected, actual) in checks.items():
    if expected != actual:
        drift.append(name)
        print(f"DRIFT={name}")

print(f"ODOO_SEMANTIC_RUNTIME_DRIFT={len(drift)}")
raise SystemExit(bool(drift))
