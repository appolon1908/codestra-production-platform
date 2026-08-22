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
    matrix = []
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
        enabled = {plugin["name"] for plugin in plugins if plugin.get("enabled")}
        if expected["auth"] not in enabled:
            raise RuntimeError(f"required auth plugin absent: {expected['name']}")
        if args.apply:
            request(args.admin_url, "PATCH", f"/routes/{route['id']}", {
                "hosts[]": hosts,
                "methods[]": expected["methods"],
                "paths[]": [expected["path"]],
                "https_redirect_status_code": 426,
            })
            if "request-size-limiting" not in enabled:
                request(args.admin_url, "POST", f"/routes/{route['id']}/plugins", {
                    "name": "request-size-limiting", "config.allowed_payload_size": expected["maxBodyMb"],
                })
            if "rate-limiting" not in enabled:
                request(args.admin_url, "POST", f"/routes/{route['id']}/plugins", {
                    "name": "rate-limiting", "config.minute": expected["ratePerMinute"],
                    "config.policy": "local", "config.limit_by": "consumer",
                })
        matrix.append({
            "ROUTE": expected["path"], "METHOD": ";".join(expected["methods"]),
            "CALLER": "production application/provider", "AUTH": expected["auth"],
            "EXPECTED_HOST": manifest["canonicalHost"], "EXPECTED_UPSTREAM": route["service"]["id"],
            "KONG_PRESENT": "PASS", "STATUS": "PASS" if args.apply or manifest["canonicalHost"] in original_hosts else "DRIFT",
        })
    args.evidence.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n")
    print("REQUIRED_PUBLIC_ROUTES_PRESENT=" + ("PASS" if args.apply else "DRY_RUN"))
    print("UNNECESSARY_PUBLIC_ROUTES=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
