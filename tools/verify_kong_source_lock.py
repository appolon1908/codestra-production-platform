#!/usr/bin/env python3
"""Verify the pinned standalone Kong source authority."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "config/kong-source.lock.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["schema"] == "codestra.platform.external-source-lock.v1"
    assert value["component"] == "kong-gateway"
    assert value["repository"] == "appolon1908-hue/Kong"
    assert SHA40.fullmatch(value["commit"])
    assert SHA40.fullmatch(value["source_platform_sha"])
    assert SHA40.fullmatch(value["source_route_sha"])
    assert value["production_state_changed"] is False
    return value


def verify_local_absence(lock: dict[str, Any], root: Path = ROOT) -> None:
    unexpected = [
        relative
        for relative in lock["local_implementation_paths_must_be_absent"]
        if (root / relative).exists()
    ]
    if unexpected:
        raise SystemExit(
            "duplicated Kong source remains in platform: " + ",".join(unexpected)
        )


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "codestra-platform-kong-source-lock/1"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def normalized_routes(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for service in document.get("services", []):
        for route in service.get("routes", []):
            rows.append(
                {
                    "service": service.get("name"),
                    "route": route.get("name"),
                    "methods": sorted(route.get("methods", ["ANY"])),
                    "paths": sorted(route.get("paths", [])),
                    "hosts": sorted(route.get("hosts", [])),
                }
            )
    return sorted(rows, key=lambda row: (row["service"], row["route"]))


def verify_online(lock: dict[str, Any]) -> None:
    base = (
        f"https://raw.githubusercontent.com/"
        f"{lock['repository']}/{lock['commit']}"
    )
    manifest = json.loads(fetch_text(f"{base}/{lock['manifest_path']}"))
    assert manifest["schema"] == lock["manifest_schema"]
    assert manifest["target_repository"] == lock["repository"]
    assert manifest["source_protected_sha"] == lock["source_platform_sha"]
    assert manifest["source_route_sha"] == lock["source_route_sha"]
    available = {row["path"] for row in manifest["files"]}
    missing = sorted(set(lock["required_paths"]) - available)
    if missing:
        raise SystemExit(
            "standalone Kong source missing required paths: " + ",".join(missing)
        )

    kong = yaml.safe_load(fetch_text(f"{base}/deploy/kong/control-plane.yml"))
    expected = sorted(
        lock["public_routes"], key=lambda row: (row["service"], row["route"])
    )
    if normalized_routes(kong) != expected:
        raise SystemExit(
            "standalone Kong public route contract differs from platform lock"
        )

    scope_policy = fetch_text(f"{base}/deploy/kong/scope-policy.lua")
    security = lock["security_contracts"]
    assert security["system_admin_required_scope"] in scope_policy
    for role in security["authenticated_role_headers"]:
        assert (
            f'set_header("X-Authenticated-Role", "{role}")'
            in scope_policy
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    lock = load_lock()
    verify_local_absence(lock)
    if args.online:
        verify_online(lock)
    print(
        f"KONG_SOURCE_AUTHORITY=PASS REPOSITORY={lock['repository']} "
        f"COMMIT={lock['commit']} ONLINE={'YES' if args.online else 'NO'}"
    )


if __name__ == "__main__":
    main()
