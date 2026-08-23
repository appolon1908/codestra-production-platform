#!/usr/bin/env python3
"""Capture secret-free Docker architecture facts for policy validation."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def docker_json(*args: str):
    return json.loads(subprocess.check_output(["docker", *args], text=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    identifiers = subprocess.check_output(["docker", "ps", "-q"], text=True).split()
    inspected = docker_json("inspect", *identifiers) if identifiers else []
    containers = []
    for item in inspected:
        ports = []
        for container_port, bindings in (item.get("HostConfig", {}).get("PortBindings") or {}).items():
            if bindings:
                ports.extend({"container_port": int(container_port.split("/", 1)[0]), "host_ip": binding.get("HostIp", ""), "host_port": int(binding["HostPort"])} for binding in bindings if binding.get("HostPort"))
        env_names = sorted(
            entry.partition("=")[0]
            for entry in item.get("Config", {}).get("Env", [])
            if any(marker in entry.partition("=")[0].upper() for marker in ("CLIENT_ID", "SERVICE_ACCOUNT", "DATABASE", "DB_"))
        )
        containers.append({
            "name": item["Name"].lstrip("/"),
            "image": item.get("Image"),
            "networks": sorted(item.get("NetworkSettings", {}).get("Networks", {})),
            "published_ports": sorted(ports, key=lambda value: (value["host_ip"], value["host_port"])),
            "identity_environment_names": env_names,
            "outbound_destinations": [],
            "unknown_service_accounts": False,
        })
    database_access = []
    query = """WITH r(role) AS (VALUES ('odoo_app'),('n8n_app'),('middleware_app'),('control_plane_app'),('email_reseller_app'),('beyvra_email')), d(db) AS (VALUES ('codestra_odoo'),('codestra_n8n'),('codestra_middleware'),('control_plane'),('email_reseller'),('beyvra_email')) SELECT role||'|'||db||'|'||has_database_privilege(role,db,'CONNECT') FROM r CROSS JOIN d ORDER BY role,db;"""
    try:
        rows = subprocess.check_output(["docker", "exec", "-u", "postgres", "codestra-postgres-1", "psql", "-XAt", "-d", "postgres", "-c", query], text=True).splitlines()
        for row in rows:
            role, database, allowed = row.split("|")
            database_access.append({"role": role, "database": database, "connect": allowed == "true"})
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        database_access = []
    payload = {
        "schema": "codestra.runtime-architecture.v1",
        "containers": sorted(containers, key=lambda value: value["name"]),
        "database_access": database_access,
        "public_endpoints": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
