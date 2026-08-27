#!/usr/bin/env python3
"""Verify the pinned standalone Kong source authority."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "config/kong-source.lock.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class SourceLockError(RuntimeError):
    """The pinned Kong source does not satisfy the platform contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceLockError(message)


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(
        value.get("schema") == "codestra.platform.external-source-lock.v1",
        "unsupported Kong source-lock schema",
    )
    require(value.get("component") == "kong-gateway", "unexpected component")
    require(
        value.get("repository") == "appolon1908-hue/Kong",
        "unexpected Kong source repository",
    )
    require(bool(SHA40.fullmatch(str(value.get("commit", "")))), "invalid commit")
    require(
        bool(SHA40.fullmatch(str(value.get("source_platform_sha", "")))),
        "invalid source platform SHA",
    )
    require(
        bool(SHA40.fullmatch(str(value.get("source_route_sha", "")))),
        "invalid source route SHA",
    )
    require(value.get("production_state_changed") is False, "unsafe lock state")
    require(
        set(value.get("external_route_contracts", {}))
        == {"callback", "campaign_automation"},
        "callback and campaign contracts must both be pinned",
    )
    return value


def verify_local_absence(lock: dict[str, Any], root: Path = ROOT) -> None:
    unexpected = [
        relative
        for relative in lock["local_implementation_paths_must_be_absent"]
        if (root / relative).exists()
    ]
    if unexpected:
        raise SourceLockError(
            "duplicated Kong source remains in platform: " + ",".join(unexpected)
        )


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "codestra-platform-kong-source-lock/2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8")
    except (OSError, UnicodeError, urllib.error.HTTPError) as exc:
        raise SourceLockError(f"unable to fetch pinned Kong source: {url}") from exc


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


def configured_service(document: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [row for row in document.get("services", []) if row.get("name") == name]
    require(len(matches) == 1, f"expected exactly one Kong service named {name}")
    return matches[0]


def configured_route(service: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [row for row in service.get("routes", []) if row.get("name") == name]
    require(len(matches) == 1, f"expected exactly one Kong route named {name}")
    return matches[0]


def effective_plugin(
    service: dict[str, Any],
    route: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    matches = [
        row
        for owner in (service, route)
        for row in owner.get("plugins", [])
        if row.get("name") == name and row.get("enabled", True) is not False
    ]
    require(
        len(matches) == 1,
        f"{route.get('name')} must inherit exactly one enabled {name} plugin",
    )
    return matches[0]


def normalized_policy(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(line.rstrip() for line in lines)


def verify_admin_security(
    document: dict[str, Any],
    scope_policy: str,
    contract: dict[str, Any],
) -> None:
    service = configured_service(document, contract["service"])
    route_contract = contract["route"]
    route = configured_route(service, route_contract["name"])
    actual_route = {key: value for key, value in route.items() if key != "plugins"}
    require(
        actual_route == route_contract,
        "system-admin route differs from its exact platform contract",
    )

    oidc = effective_plugin(service, route, "openid-connect")
    require(
        oidc.get("config") == contract["openid_connect_config"],
        "system-admin route OIDC configuration drifted",
    )

    pre_function = effective_plugin(service, route, "pre-function")
    require(
        set(pre_function) <= {"name", "config", "enabled", "tags", "instance_name"},
        "system-admin pre-function contains unreviewed fields",
    )
    access = pre_function.get("config", {}).get("access")
    require(
        isinstance(access, list)
        and len(access) == 1
        and isinstance(access[0], str),
        "system-admin route must have one pre-function access policy",
    )
    require(
        normalized_policy(access[0]) == normalized_policy(scope_policy),
        "inline pre-function policy differs from pinned scope-policy.lua",
    )

    policy = normalized_policy(access[0])
    require(
        f'required = "{contract["required_scope"]}"' in policy,
        "system-admin scope is not enforced by the attached policy",
    )
    for role in contract["authenticated_role_headers"]:
        require(
            f'set_header("X-Authenticated-Role", "{role}")' in policy,
            f"attached policy does not emit the reviewed {role} role",
        )


def verify_exact_contract(
    name: str,
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    if actual != expected:
        actual_text = json.dumps(actual, sort_keys=True, separators=(",", ":"))
        expected_text = json.dumps(expected, sort_keys=True, separators=(",", ":"))
        raise SourceLockError(
            f"{name} contract drifted: expected={expected_text} actual={actual_text}"
        )


def verify_online(lock: dict[str, Any]) -> None:
    base = (
        "https://raw.githubusercontent.com/"
        f"{lock['repository']}/{lock['commit']}"
    )
    manifest = json.loads(fetch_text(f"{base}/{lock['manifest_path']}"))
    require(
        manifest.get("schema") == lock["manifest_schema"],
        "standalone Kong migration-manifest schema drifted",
    )
    require(
        manifest.get("target_repository") == lock["repository"],
        "standalone Kong migration-manifest repository drifted",
    )
    require(
        manifest.get("source_protected_sha") == lock["source_platform_sha"],
        "standalone Kong source-platform SHA drifted",
    )
    require(
        manifest.get("source_route_sha") == lock["source_route_sha"],
        "standalone Kong route-authority SHA drifted",
    )
    available = {row["path"] for row in manifest.get("files", [])}
    missing = sorted(set(lock["required_paths"]) - available)
    require(
        not missing,
        "standalone Kong source missing required paths: " + ",".join(missing),
    )

    kong = yaml.safe_load(fetch_text(f"{base}/deploy/kong/control-plane.yml"))
    expected_routes = sorted(
        lock["public_routes"], key=lambda row: (row["service"], row["route"])
    )
    require(
        normalized_routes(kong) == expected_routes,
        "standalone Kong public route contract differs from platform lock",
    )

    security = lock["security_contracts"]["system_admin"]
    scope_policy = fetch_text(f"{base}/{security['policy_path']}")
    verify_admin_security(kong, scope_policy, security)

    for name, contract in lock["external_route_contracts"].items():
        document = json.loads(fetch_text(f"{base}/{contract['path']}"))
        verify_exact_contract(name, document, contract["document"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    try:
        lock = load_lock()
        verify_local_absence(lock)
        if args.online:
            verify_online(lock)
    except (KeyError, TypeError, ValueError, yaml.YAMLError, SourceLockError) as exc:
        print(f"KONG_SOURCE_AUTHORITY=FAIL ERROR={exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(
        f"KONG_SOURCE_AUTHORITY=PASS REPOSITORY={lock['repository']} "
        f"COMMIT={lock['commit']} ONLINE={'YES' if args.online else 'NO'}"
    )


if __name__ == "__main__":
    main()
