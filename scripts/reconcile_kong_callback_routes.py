#!/usr/bin/env python3
"""Idempotently reconcile the bounded callback API surface in Kong."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request(base, method, path, payload=None):
    data = None if payload is None else urlencode(payload, doseq=True).encode()
    try:
        with urlopen(Request(base.rstrip("/") + path, data=data, method=method), timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        raise RuntimeError("Kong Admin API rejected %s %s (%s)" % (method, path, error.code)) from error


def singleton(base, resource, name):
    rows = request(base, "GET", "/%s?%s" % (resource, urlencode({"name": name}))).get("data", [])
    if len(rows) > 1:
        raise RuntimeError("duplicate Kong %s named %s" % (resource, name))
    return rows[0] if rows else None


def require_equal(actual, expected, label):
    if actual != expected:
        raise RuntimeError("Kong readback mismatch for %s" % label)


def verify_service(service, expected):
    for field in ("name", "protocol", "host", "port", "retries",
                  "connect_timeout", "read_timeout", "write_timeout"):
        require_equal(service.get(field), expected[field], "service.%s" % field)


def verify_route(route, expected, service_id, host):
    require_equal(route.get("service", {}).get("id"), service_id, expected["name"] + ".service")
    require_equal(route.get("hosts"), [host], expected["name"] + ".hosts")
    require_equal(route.get("paths"), expected["paths"], expected["name"] + ".paths")
    require_equal(sorted(route.get("methods") or []), sorted(expected["methods"]), expected["name"] + ".methods")
    require_equal(route.get("protocols"), ["https"], expected["name"] + ".protocols")
    require_equal(route.get("strip_path"), expected["strip_path"], expected["name"] + ".strip_path")


def verify_plugins(by_name, expected, spec):
    required = {"request-size-limiting", "rate-limiting", "correlation-id", "openid-connect"}
    if not required <= set(by_name):
        raise RuntimeError("callback route lacks security plugins: %s" % expected["name"])
    require_equal(by_name["request-size-limiting"]["config"].get("allowed_payload_size"), expected["maxBodyMb"], expected["name"] + ".body_limit")
    rate = by_name["rate-limiting"]["config"]
    require_equal(rate.get("minute"), expected["ratePerMinute"], expected["name"] + ".rate")
    require_equal(rate.get("policy"), "local", expected["name"] + ".rate_policy")
    oidc = by_name["openid-connect"]["config"]
    require_equal(oidc.get("issuer"), spec["oidcIssuer"], expected["name"] + ".issuer")
    require_equal(oidc.get("auth_methods"), ["bearer"], expected["name"] + ".auth_methods")
    require_equal(oidc.get("audience"), [spec["audience"]], expected["name"] + ".audience")
    require_equal(oidc.get("scopes_required"), [expected["requiredScope"]], expected["name"] + ".scope")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--manifest", type=Path, default=Path("config/kong-callback-routes.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_text())
    service_spec = spec["service"]
    service = singleton(args.admin_url, "services", service_spec["name"])
    if args.apply:
        endpoint = "/services/%s" % service["id"] if service else "/services"
        service = request(args.admin_url, "PATCH" if service else "POST", endpoint, service_spec)
    elif not service:
        raise RuntimeError("callback service is absent (dry run)")
    service = singleton(args.admin_url, "services", service_spec["name"])
    verify_service(service, service_spec)

    for expected in spec["routes"]:
        route = singleton(args.admin_url, "routes", expected["name"])
        payload = {
            "name": expected["name"], "service.id": service["id"],
            "hosts[]": [spec["host"]], "paths[]": expected["paths"],
            "methods[]": expected["methods"], "protocols[]": ["https"],
            "strip_path": str(expected["strip_path"]).lower(),
            "preserve_host": "true", "https_redirect_status_code": 426,
        }
        if args.apply:
            endpoint = "/routes/%s" % route["id"] if route else "/routes"
            route = request(args.admin_url, "PATCH" if route else "POST", endpoint, payload)
        elif not route:
            raise RuntimeError("callback route is absent: %s" % expected["name"])
        route = singleton(args.admin_url, "routes", expected["name"])
        verify_route(route, expected, service["id"], spec["host"])
        plugins = request(args.admin_url, "GET", "/routes/%s/plugins" % route["id"]).get("data", [])
        by_name = {plugin["name"]: plugin for plugin in plugins if plugin.get("enabled")}
        controls = {
            "request-size-limiting": {"config.allowed_payload_size": expected["maxBodyMb"]},
            "rate-limiting": {"config.minute": expected["ratePerMinute"], "config.policy": "local", "config.limit_by": "ip"},
            "correlation-id": {"config.header_name": "X-Correlation-ID", "config.generator": "uuid", "config.echo_downstream": "true"},
            "openid-connect": {
                "config.issuer": spec["oidcIssuer"],
                "config.auth_methods[]": ["bearer"],
                "config.audience[]": [spec["audience"]],
                "config.scopes_required[]": [expected["requiredScope"]],
            },
        }
        for name, config in controls.items():
            current = by_name.get(name)
            if args.apply:
                endpoint = "/plugins/%s" % current["id"] if current else "/routes/%s/plugins" % route["id"]
                request(args.admin_url, "PATCH" if current else "POST", endpoint, {"name": name, **config})
        plugins = request(args.admin_url, "GET", "/routes/%s/plugins" % route["id"]).get("data", [])
        verify_plugins({plugin["name"]: plugin for plugin in plugins if plugin.get("enabled")}, expected, spec)
    print("KONG_CALLBACK_ROUTES=%s" % ("APPLIED" if args.apply else "PASS"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
