#!/usr/bin/env python3
"""Check or apply the reviewed production Kong route boundary contract."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "deploy/kong-production-standby/kong/production-route-hardening.json"
BREERO_INSTANCE = "breero-strip-spoofable-identity"
BREERO_HEADERS = [
    "X-Codestra-Subject", "X-Codestra-Tenant", "X-Codestra-Roles",
    "X-Codestra-Scopes", "X-Authenticated-User", "X-Consumer-ID",
    "X-Consumer-Custom-ID",
]


def request(admin: str, path: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    req = urllib.request.Request(
        admin.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def normalized(route: dict) -> dict:
    return {
        "hosts": sorted(route.get("hosts") or []),
        "protocols": sorted(route.get("protocols") or []),
        "methods": sorted(route.get("methods") or []),
    }


def transformer_payload(route_id: str) -> dict:
    empty = {"headers": [], "querystring": [], "body": []}
    return {
        "name": "request-transformer",
        "instance_name": BREERO_INSTANCE,
        "route": {"id": route_id},
        "tags": ["breero-production", "security-boundary"],
        "config": {
            "remove": {**empty, "headers": BREERO_HEADERS},
            "rename": empty,
            "replace": {**empty, "uri": None},
            "add": empty,
            "append": empty,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin", default="http://127.0.0.1:8001")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.admin)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Kong Admin must be accessed through loopback HTTP")

    desired = json.loads(args.contract.read_text())["routes"]
    live_routes = {item["name"]: item for item in request(args.admin, "/routes")["data"]}
    missing = sorted(set(desired) - set(live_routes))
    drift = {
        name: {"desired": normalized(config), "actual": normalized(live_routes[name])}
        for name, config in desired.items()
        if name in live_routes and normalized(config) != normalized(live_routes[name])
    }
    if missing:
        print(json.dumps({"status": "BLOCKED", "missing_routes": missing}, sort_keys=True))
        return 2

    if args.apply:
        for name in sorted(drift):
            config = desired[name]
            request(args.admin, "/routes/" + urllib.parse.quote(name), "PATCH", {
                "hosts": config["hosts"], "protocols": config["protocols"],
                "methods": config["methods"], "https_redirect_status_code": 426,
            })

    plugins = request(args.admin, "/plugins")["data"]
    breero_id = live_routes["breero-production-api-route"]["id"]
    matches = [p for p in plugins if (p.get("route") or {}).get("id") == breero_id and p.get("instance_name") == BREERO_INSTANCE]
    plugin_ok = len(matches) == 1 and sorted(matches[0]["config"]["remove"]["headers"]) == sorted(BREERO_HEADERS)
    if args.apply and not plugin_ok:
        payload = transformer_payload(breero_id)
        if matches:
            request(args.admin, "/plugins/" + matches[0]["id"], "PATCH", payload)
        else:
            request(args.admin, "/plugins", "POST", payload)

    if args.apply:
        return main_check(args.admin, desired)
    status = "PASS" if not drift and plugin_ok else "DRIFT"
    print(json.dumps({"status": status, "route_drift": sorted(drift), "breero_header_strip": plugin_ok}, sort_keys=True))
    return 0 if status == "PASS" else 1


def main_check(admin: str, desired: dict) -> int:
    live = {item["name"]: item for item in request(admin, "/routes")["data"]}
    drift = [name for name, config in desired.items() if normalized(config) != normalized(live[name])]
    plugins = request(admin, "/plugins")["data"]
    route_id = live["breero-production-api-route"]["id"]
    matches = [p for p in plugins if (p.get("route") or {}).get("id") == route_id and p.get("instance_name") == BREERO_INSTANCE]
    plugin_ok = len(matches) == 1 and sorted(matches[0]["config"]["remove"]["headers"]) == sorted(BREERO_HEADERS)
    status = "PASS" if not drift and plugin_ok else "DRIFT"
    print(json.dumps({"status": status, "route_drift": sorted(drift), "breero_header_strip": plugin_ok}, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"status": "ERROR", "detail": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(3)
