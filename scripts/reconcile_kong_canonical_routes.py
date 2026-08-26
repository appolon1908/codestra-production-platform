#!/usr/bin/env python3
"""Fail-closed canonical-host reconciliation for proven public Kong routes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request(base: str, method: str, path: str, payload=None):
    data = None if payload is None else urlencode(payload, doseq=True).encode()
    with urlopen(Request(base.rstrip("/") + path, method=method, data=data), timeout=10) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--manifest", type=Path, default=Path("config/kong-canonical-middleware-routes.json"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    all_routes = request(args.admin_url, "GET", "/routes?size=1000")["data"]
    managed_names = {route["name"] for route in manifest["routes"]}
    contract_names = {route["name"] for route in manifest.get("contractRoutes", [])}
    allowed_names = managed_names | contract_names | set(manifest.get("allowedExistingRouteNames", []))
    unexpected_public = sorted(
        route.get("name") or route["id"] for route in all_routes
        if manifest["canonicalHost"] in (route.get("hosts") or [])
        and route.get("name") not in allowed_names
    )
    matrix = []
    services = request(args.admin_url, "GET", "/services?size=1000")["data"]
    service_by_id = {service["id"]: service for service in services}
    for expected in manifest.get("contractRoutes", []):
        matches = [route for route in all_routes if route.get("name") == expected["name"]]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one contract route: {expected['name']}")
        route = matches[0]
        for field in ("hosts", "paths", "methods"):
            if sorted(route.get(field) or []) != sorted(expected[field]):
                raise RuntimeError(f"contract {field} drift: {expected['name']}")
        service = service_by_id[route["service"]["id"]]
        if service.get("host") != expected["serviceHost"] or service.get("port") != expected["servicePort"]:
            raise RuntimeError(f"contract upstream drift: {expected['name']}")
        plugins = request(args.admin_url, "GET", f"/routes/{route['id']}/plugins")["data"]
        enabled = {plugin["name"] for plugin in plugins if plugin.get("enabled")}
        missing = set(expected["requiredPlugins"]) - enabled
        if missing:
            raise RuntimeError(f"contract plugin drift: {expected['name']}: {sorted(missing)}")
        matrix.append({
            "ROUTE": ";".join(expected["paths"]),
            "METHOD": ";".join(expected["methods"]),
            "CALLER": "authenticated Codestra client",
            "AUTH": "jwt",
            "EXPECTED_HOST": ";".join(expected["hosts"]),
            "EXPECTED_UPSTREAM": f"{expected['serviceHost']}:{expected['servicePort']}",
            "KONG_PRESENT": "PASS",
            "STATUS": "PASS",
        })
    for expected in manifest["routes"]:
        matches = request(args.admin_url, "GET", "/routes?" + urlencode({"name": expected["name"]}))["data"]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one existing route: {expected['name']}")
        route = matches[0]
        if sorted(route.get("paths") or []) != [expected["path"]] or sorted(route.get("methods") or []) != sorted(expected["methods"]):
            raise RuntimeError(f"source/live method or path drift: {expected['name']}")
        original_hosts = route.get("hosts") or []
        hosts = sorted(set(original_hosts + [manifest["canonicalHost"], manifest["legacyHost"]]))
        plugins = request(args.admin_url, "GET", f"/routes/{route['id']}/plugins")["data"]
        enabled_plugins = {plugin["name"]: plugin for plugin in plugins if plugin.get("enabled")}
        enabled = set(enabled_plugins)
        if expected["auth"] not in enabled:
            raise RuntimeError(f"required auth plugin absent: {expected['name']}")
        if args.apply:
            request(args.admin_url, "PATCH", f"/routes/{route['id']}", {
                "hosts[]": hosts,
                "methods[]": expected["methods"],
                "paths[]": [expected["path"]],
                "https_redirect_status_code": 426,
            })
            if "request-size-limiting" in enabled:
                request(args.admin_url, "PATCH", f"/plugins/{enabled_plugins['request-size-limiting']['id']}", {
                    "config.allowed_payload_size": expected["maxBodyMb"],
                })
            else:
                request(args.admin_url, "POST", f"/routes/{route['id']}/plugins", {
                    "name": "request-size-limiting", "config.allowed_payload_size": expected["maxBodyMb"],
                })
            if "rate-limiting" in enabled:
                request(args.admin_url, "PATCH", f"/plugins/{enabled_plugins['rate-limiting']['id']}", {
                    "config.minute": expected["ratePerMinute"], "config.policy": "local",
                    "config.limit_by": "consumer",
                })
            else:
                request(args.admin_url, "POST", f"/routes/{route['id']}/plugins", {
                    "name": "rate-limiting", "config.minute": expected["ratePerMinute"],
                    "config.policy": "local", "config.limit_by": "consumer",
                })
            verified = {plugin["name"]: plugin for plugin in request(args.admin_url, "GET", f"/routes/{route['id']}/plugins")["data"] if plugin.get("enabled")}
            size = verified.get("request-size-limiting", {}).get("config", {}).get("allowed_payload_size")
            rate = verified.get("rate-limiting", {}).get("config", {})
            if size != expected["maxBodyMb"] or rate.get("minute") != expected["ratePerMinute"] or rate.get("policy") != "local" or rate.get("limit_by") != "consumer":
                raise RuntimeError(f"limiter readback mismatch: {expected['name']}")
        matrix.append({
            "ROUTE": expected["path"], "METHOD": ";".join(expected["methods"]),
            "CALLER": "production application/provider", "AUTH": expected["auth"],
            "EXPECTED_HOST": manifest["canonicalHost"], "EXPECTED_UPSTREAM": route["service"]["id"],
            "KONG_PRESENT": "PASS", "STATUS": "PASS" if args.apply or manifest["canonicalHost"] in original_hosts else "DRIFT",
        })
    args.evidence.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n")
    print("REQUIRED_PUBLIC_ROUTES_PRESENT=" + ("PASS" if args.apply else "DRY_RUN"))
    print(f"UNNECESSARY_PUBLIC_ROUTES={len(unexpected_public)}")
    if unexpected_public:
        print("UNEXPECTED_PUBLIC_ROUTE_NAMES=" + ";".join(unexpected_public))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
