#!/usr/bin/env python3
"""Idempotently apply private, mock-only Kong standby routes.

This script never creates a route for api.codestra.co and never targets a
provider. It is safe to rerun and tags every object for exact rollback.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ADMIN = "http://127.0.0.1:8001"
TAG = "codestra-kong-standby-20260820"
HOST = "kong-standby.internal.codestra.agency"
ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "deploy/kong-production-standby/kong/standby.json").read_text())


def request(method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(ADMIN + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Kong Admin {method} {path}: {exc.code} {detail}") from exc


def upsert(collection: str, name: str, payload: dict):
    query = urllib.parse.urlencode({"name": name})
    existing = request("GET", f"/{collection}?{query}").get("data", [])
    if existing:
        return request("PATCH", f"/{collection}/{existing[0]['id']}", payload)
    return request("POST", f"/{collection}", payload)


def plugin(route_id: str, name: str, config: dict):
    current = request("GET", f"/routes/{route_id}/plugins").get("data", [])
    matches = [item for item in current if item["name"] == name and TAG in (item.get("tags") or [])]
    payload = {"name": name, "enabled": True, "config": config, "tags": [TAG]}
    if matches:
        return request("PATCH", f"/plugins/{matches[0]['id']}", payload)
    return request("POST", f"/routes/{route_id}/plugins", payload)


def main():
    applied = []
    for item in CONFIG["services"]:
        service = upsert("services", item["name"], {
            "name": item["name"], "protocol": "http", "host": "codestra-kong-standby-auth",
            "port": 8080, "path": None, "retries": 0,
            "connect_timeout": item["connectTimeoutMs"],
            "write_timeout": item["writeTimeoutMs"], "read_timeout": item["readTimeoutMs"],
            "tags": [TAG, "mock-only", "no-provider-delivery"],
        })
        route_name = item["name"] + "-route"
        route = upsert("routes", route_name, {
            "name": route_name, "service": {"id": service["id"]},
            "hosts": [HOST], "paths": [item["path"]], "methods": item["methods"],
            "protocols": ["http", "https"], "strip_path": False,
            "preserve_host": False, "tags": [TAG, "private-staging-only"],
        })
        plugin(route["id"], "request-transformer", {
            "remove": {"headers": CONFIG["trustedHeadersToStrip"]},
        })
        plugin(route["id"], "request-size-limiting", {
            "allowed_payload_size": item["bodyLimitBytes"], "size_unit": "bytes",
            "require_content_length": True,
        })
        plugin(route["id"], "rate-limiting", {
            "minute": item["ratePerMinute"], "limit_by": "ip", "policy": "local",
            "fault_tolerant": False, "hide_client_headers": False,
        })
        applied.append(route_name)
    print("KONG_PRIVATE_STANDBY_APPLY=PASS")
    print("ROUTES=" + ",".join(applied))
    print("PUBLIC_HOST_ATTACHED=NO")


if __name__ == "__main__":
    main()
