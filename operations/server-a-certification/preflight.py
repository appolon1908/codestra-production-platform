#!/usr/bin/env python3
"""Read-only Server A baseline and source-attribution collector."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PACKAGE = Path(__file__).resolve().parents[1] / "database-certification"
sys.path.insert(0, str(DB_PACKAGE))
from runtime_contract import ContractError, atomic_write, atomic_write_json, run_command  # noqa: E402

TARGET_PUBLIC_IP = "65.109.65.169"
TARGET_PRIVATE_IP = "10.40.0.1"
DEFAULT_OUTPUT = Path("/opt/codestra/evidence/server-a-certification/preflight")


def load_firewall_module():
    path = Path(__file__).resolve().parent / "firewall" / "server-a-firewall.py"
    spec = importlib.util.spec_from_file_location("server_a_firewall", path)
    if spec is None or spec.loader is None:
        raise ContractError("cannot load firewall SSH-state collector")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def command_text(args: list[str], *, check: bool = True) -> str:
    return run_command(args, check=check, timeout=120).stdout.decode("utf-8", "replace").strip()


def host_addresses() -> set[str]:
    payload = json.loads(run_command(["ip", "-j", "address", "show"], timeout=30).stdout)
    addresses: set[str] = set()
    for interface in payload:
        for item in interface.get("addr_info") or []:
            local = item.get("local")
            if local:
                addresses.add(str(local))
    return addresses


def git_state(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        raise ContractError(f"repository is not a Git working tree: {root}")

    def git(*args: str, check: bool = True) -> str:
        return command_text(["git", "-C", str(root), *args], check=check)

    return {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "remote": git("remote", "get-url", "origin"),
        "status_porcelain": git("status", "--porcelain=v1"),
        "exact_tag": git("describe", "--tags", "--exact-match", check=False),
    }


def docker_inventory() -> dict[str, Any]:
    ids = command_text(["docker", "ps", "-q"]).splitlines()
    ids = [value.strip() for value in ids if value.strip()]
    inspected = [] if not ids else json.loads(run_command(["docker", "inspect", *ids], timeout=180).stdout)
    records: list[dict[str, Any]] = []
    published_count = 0
    for item in inspected:
        config = item.get("Config") or {}
        labels = config.get("Labels") or {}
        host = item.get("HostConfig") or {}
        bindings = host.get("PortBindings") or {}
        ports: list[str] = []
        for container_port, entries in bindings.items():
            for entry in entries or []:
                ports.append(
                    f"{entry.get('HostIp') or '0.0.0.0'}:{entry.get('HostPort') or '*'}->{container_port}"
                )
        published_count += len(ports)
        health_test = (config.get("Healthcheck") or {}).get("Test") or []
        image_reference = str(config.get("Image") or "")
        records.append(
            {
                "container_id": item.get("Id", "")[:12],
                "container_name": str(item.get("Name", "")).lstrip("/"),
                "compose_project": labels.get("com.docker.compose.project"),
                "compose_service": labels.get("com.docker.compose.service"),
                "image_reference": image_reference,
                "image_id": item.get("Image"),
                "oci_source": labels.get("org.opencontainers.image.source"),
                "oci_revision": labels.get("org.opencontainers.image.revision"),
                "digest_pinned_reference": "@sha256:" in image_reference,
                "healthcheck_present": bool(health_test) and health_test != ["NONE"],
                "restart_policy": (host.get("RestartPolicy") or {}).get("Name") or "no",
                "memory_limit_bytes": int(host.get("Memory") or 0),
                "nano_cpus": int(host.get("NanoCpus") or 0),
                "pid_limit": int(host.get("PidsLimit") or 0),
                "published_ports": sorted(ports),
                "networks": sorted((item.get("NetworkSettings", {}).get("Networks") or {}).keys()),
                "mounts": [
                    {
                        "type": mount.get("Type"),
                        "name": mount.get("Name"),
                        "destination": mount.get("Destination"),
                        "rw": bool(mount.get("RW")),
                    }
                    for mount in item.get("Mounts") or []
                ],
            }
        )
    return {
        "running_container_count": len(records),
        "published_port_mapping_count": published_count,
        "records": records,
    }


def systemd_state() -> dict[str, Any]:
    return {
        "failed_units": command_text(
            ["systemctl", "list-units", "--failed", "--no-legend", "--plain"], check=False
        ).splitlines(),
        "timers": command_text(
            ["systemctl", "list-timers", "--all", "--no-legend", "--plain"], check=False
        ).splitlines(),
    }


def firewall_state() -> dict[str, Any]:
    nft = command_text(["nft", "list", "ruleset"], check=False)
    ufw = command_text(["ufw", "status", "verbose"], check=False)
    return {"nft_ruleset": nft, "ufw_status": ufw}


def write_tsv(path: Path, docker: dict[str, Any]) -> None:
    header = [
        "container", "project", "service", "image", "digest_pinned", "oci_source",
        "oci_revision", "healthcheck", "restart_policy", "memory_limit_bytes",
        "nano_cpus", "pid_limit", "published_ports",
    ]
    lines = ["\t".join(header)]
    for record in docker["records"]:
        values = [
            record["container_name"],
            record.get("compose_project") or "",
            record.get("compose_service") or "",
            record["image_reference"],
            "PASS" if record["digest_pinned_reference"] else "FAIL",
            record.get("oci_source") or "",
            record.get("oci_revision") or "",
            "PASS" if record["healthcheck_present"] else "FAIL",
            record["restart_policy"],
            str(record["memory_limit_bytes"]),
            str(record["nano_cpus"]),
            str(record["pid_limit"]),
            ",".join(record["published_ports"]),
        ]
        lines.append("\t".join(value.replace("\t", " ").replace("\n", " ") for value in values))
    atomic_write(path, ("\n".join(lines) + "\n").encode("utf-8"), mode=0o600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository-root", type=Path, default=Path("/root/codestra-production-completion")
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        addresses = host_addresses()
        if TARGET_PUBLIC_IP not in addresses or TARGET_PRIVATE_IP not in addresses:
            raise ContractError(
                f"host identity mismatch: expected {TARGET_PUBLIC_IP} and {TARGET_PRIVATE_IP}"
            )
        git = git_state(args.repository_root)
        docker = docker_inventory()
        firewall_module = load_firewall_module()
        payload = {
            "schema": "codestra.server-a-preflight.v1",
            "status": "PASS",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "target_server": TARGET_PUBLIC_IP,
            "target_private_ip": TARGET_PRIVATE_IP,
            "host_addresses": sorted(addresses),
            "hostname": command_text(["hostname", "--fqdn"], check=False),
            "kernel": command_text(["uname", "-a"]),
            "git": git,
            "docker": docker,
            "systemd": systemd_state(),
            "firewall": firewall_state(),
            "ssh_read_only_baseline": firewall_module.ssh_state(),
            "mutations_performed": False,
            "production_business_writes_executed": False,
        }
        args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write_json(args.output / "preflight.json", payload)
        write_tsv(args.output / "runtime-inventory.tsv", docker)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SERVER_A_PREFLIGHT=FAIL:{str(exc)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
