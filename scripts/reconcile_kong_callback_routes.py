#!/usr/bin/env python3
"""Idempotently reconcile the bounded callback API surface in Kong."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request(base, method, path, payload=None):
    data = None if payload is None else urlencode(payload, doseq=True).encode()
    url = path if path.startswith(("http://", "https://")) else base.rstrip("/") + path
    try:
        with urlopen(Request(url, data=data, method=method), timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        raise RuntimeError("Kong Admin API rejected %s %s (%s)" % (method, path, error.code)) from error


def request_json(base, method, path, payload):
    url = path if path.startswith(("http://", "https://")) else base.rstrip("/") + path
    try:
        req = Request(
            url, data=json.dumps(payload).encode(), method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        raise RuntimeError("Kong Admin API rejected %s %s (%s)" % (method, path, error.code)) from error


def all_rows(base, path):
    rows = []
    seen = set()
    while path:
        if path in seen:
            raise RuntimeError("Kong pagination loop detected")
        seen.add(path)
        page = request(base, "GET", path)
        rows.extend(page.get("data", []))
        path = page.get("next")
    return rows


def singleton(base, resource, name):
    rows = request(base, "GET", "/%s?%s" % (resource, urlencode({"name": name}))).get("data", [])
    if len(rows) > 1:
        raise RuntimeError("duplicate Kong %s named %s" % (resource, name))
    return rows[0] if rows else None


def one(rows, label):
    if len(rows) > 1:
        raise RuntimeError("ambiguous Kong %s" % label)
    return rows[0] if rows else None


def select_managed_route(routes, expected, host, apply):
    """Select the named route or safely adopt one overlapping legacy route."""
    named = [route for route in routes if route.get("name") == expected["name"]]
    route = one(named, "route named %s" % expected["name"])
    expected_paths = set(expected["paths"])
    expected_methods = set(expected["methods"])
    overlaps = [
        candidate for candidate in routes
        if candidate.get("id") != (route or {}).get("id")
        and host in (candidate.get("hosts") or [])
        and expected_paths.intersection(candidate.get("paths") or [])
        and expected_methods.intersection(candidate.get("methods") or [])
    ]
    if route and overlaps:
        raise RuntimeError("conflicting live route for %s%s" % (host, expected["paths"][0]))
    if route:
        return route
    exact = [
        candidate for candidate in overlaps
        if candidate.get("hosts") == [host]
        and set(candidate.get("paths") or []) == expected_paths
        and set(candidate.get("methods") or []) == expected_methods
        and candidate.get("protocols") == ["https"]
        and candidate.get("strip_path") == expected["strip_path"]
        and not (candidate.get("headers") or {})
        and not (candidate.get("snis") or [])
        and not (candidate.get("sources") or [])
        and not (candidate.get("destinations") or [])
    ]
    if overlaps and len(exact) != len(overlaps):
        raise RuntimeError("partial legacy route overlap for %s%s" % (host, expected["paths"][0]))
    collision = one(exact, "legacy route for %s%s" % (host, expected["paths"][0]))
    if collision and not apply:
        raise RuntimeError("legacy callback route requires managed adoption")
    return collision


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
    require_equal(route.get("preserve_host"), True, expected["name"] + ".preserve_host")
    require_equal(route.get("https_redirect_status_code"), 426, expected["name"] + ".https_redirect")
    require_equal(route.get("headers") or {}, {}, expected["name"] + ".headers")
    for field in ("snis", "sources", "destinations"):
        require_equal(route.get(field) or [], [], expected["name"] + "." + field)


def route_matches(route, expected, service_id, host):
    if not route:
        return False
    try:
        verify_route(route, expected, service_id, host)
        return True
    except RuntimeError:
        return False


def verify_oidc(plugin, expected, spec):
    if not plugin or not plugin.get("enabled"):
        raise RuntimeError("callback route lacks enabled OIDC: %s" % expected["name"])
    oidc = plugin["config"]
    require_equal(oidc.get("issuer"), spec["oidcIssuer"], expected["name"] + ".issuer")
    require_equal(oidc.get("auth_methods"), ["bearer"], expected["name"] + ".auth_methods")
    require_equal(oidc.get("audience_required"), [spec["audience"]], expected["name"] + ".audience")
    require_equal(oidc.get("scopes_required"), [expected["requiredScope"]], expected["name"] + ".scope")
    require_equal(oidc.get("bearer_token_param_type"), ["header"], expected["name"] + ".bearer_source")
    require_equal(oidc.get("verify_signature"), True, expected["name"] + ".signature")
    require_equal(oidc.get("verify_claims"), True, expected["name"] + ".claims")
    require_equal(oidc.get("ssl_verify"), True, expected["name"] + ".tls")
    require_equal(oidc.get("anonymous"), None, expected["name"] + ".anonymous")


def oidc_matches(plugin, expected, spec):
    try:
        verify_oidc(plugin, expected, spec)
        return True
    except RuntimeError:
        return False


def verify_plugins(by_name, expected, spec):
    required = {"request-size-limiting", "rate-limiting", "correlation-id", "openid-connect"}
    if not required <= set(by_name):
        raise RuntimeError("callback route lacks security plugins: %s" % expected["name"])
    require_equal(by_name["request-size-limiting"]["config"].get("allowed_payload_size"), expected["maxBodyMb"], expected["name"] + ".body_limit")
    rate = by_name["rate-limiting"]["config"]
    require_equal(rate.get("minute"), expected["ratePerMinute"], expected["name"] + ".rate")
    require_equal(rate.get("policy"), "local", expected["name"] + ".rate_policy")
    require_equal(rate.get("limit_by"), "ip", expected["name"] + ".rate_identity")
    correlation = by_name["correlation-id"]["config"]
    require_equal(correlation.get("header_name"), "X-Correlation-ID", expected["name"] + ".correlation_header")
    require_equal(correlation.get("generator"), "uuid", expected["name"] + ".correlation_generator")
    require_equal(correlation.get("echo_downstream"), True, expected["name"] + ".correlation_echo")
    verify_oidc(by_name["openid-connect"], expected, spec)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--manifest", type=Path, default=Path("config/kong-callback-routes.json"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest_bytes = args.manifest.read_bytes()
    spec = json.loads(manifest_bytes)
    evidence = {"checked_at": datetime.now(UTC).isoformat(),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "mode": "apply" if args.apply else "dry-run", "routes": []}
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
        routes = all_rows(args.admin_url, "/routes?size=1000")
        route = select_managed_route(routes, expected, spec["host"], args.apply)
        route_was_missing = route is None
        existing_plugins = [] if not route else request(
            args.admin_url, "GET", "/routes/%s/plugins" % route["id"]
        ).get("data", [])
        existing_by_name = {plugin["name"]: plugin for plugin in existing_plugins}
        needs_quarantine = (
            (route or {}).get("name") != expected["name"]
            or
            not route_matches(route, expected, service["id"], spec["host"])
            or not oidc_matches(existing_by_name.get("openid-connect"), expected, spec)
        )
        payload = {
            "name": expected["name"], "service": {"id": service["id"]},
            "hosts": [spec["host"]], "paths": expected["paths"],
            "methods": expected["methods"], "protocols": ["https"],
            "strip_path": expected["strip_path"], "preserve_host": True,
            "https_redirect_status_code": 426, "headers": {}, "snis": [],
        }
        if args.apply:
            endpoint = "/routes/%s" % route["id"] if route else "/routes"
            if needs_quarantine:
                quarantined = dict(payload)
                quarantined["hosts"] = ["callback-route-disabled.invalid"]
                # A new route cannot match the protected callback methods until
                # its enforced deny plugin has been installed and read back.
                if not route:
                    quarantined["methods"] = ["OPTIONS"]
                route = request_json(args.admin_url, "PATCH" if route else "POST", endpoint, quarantined)
        elif not route:
            raise RuntimeError("callback route is absent: %s" % expected["name"])
        route = singleton(args.admin_url, "routes", expected["name"])
        if args.apply and needs_quarantine:
            require_equal(route.get("hosts"), ["callback-route-disabled.invalid"], expected["name"] + ".quarantine")
            if route_was_missing:
                require_equal(route.get("methods"), ["OPTIONS"], expected["name"] + ".quarantine_methods")
        else:
            verify_route(route, expected, service["id"], spec["host"])
        plugins = request(args.admin_url, "GET", "/routes/%s/plugins" % route["id"]).get("data", [])
        by_name = {plugin["name"]: plugin for plugin in plugins}
        deny = one(
            [plugin for plugin in plugins if plugin["name"] == "request-termination"],
            "callback deny plugin",
        )
        if not args.apply and deny and deny.get("enabled"):
            raise RuntimeError("callback route has an enabled deny plugin")
        if args.apply and needs_quarantine:
            deny_config = {
                "name": "request-termination", "enabled": "true",
                "config.status_code": 503,
                "config.message": "callback route maintenance",
            }
            endpoint = "/plugins/%s" % deny["id"] if deny else "/routes/%s/plugins" % route["id"]
            request(args.admin_url, "PATCH" if deny else "POST", endpoint, deny_config)
            deny_plugins = request(args.admin_url, "GET", "/routes/%s/plugins" % route["id"]).get("data", [])
            deny = one([plugin for plugin in deny_plugins if plugin["name"] == "request-termination"], "callback deny plugin")
            require_equal(deny.get("enabled"), True, expected["name"] + ".deny_enabled")
            require_equal(deny.get("config", {}).get("status_code"), 503, expected["name"] + ".deny_status")
            require_equal(deny.get("config", {}).get("message"), "callback route maintenance", expected["name"] + ".deny_message")
        controls = {
            "request-size-limiting": {"config.allowed_payload_size": expected["maxBodyMb"]},
            "rate-limiting": {"config.minute": expected["ratePerMinute"], "config.policy": "local", "config.limit_by": "ip"},
            "correlation-id": {"config.header_name": "X-Correlation-ID", "config.generator": "uuid", "config.echo_downstream": "true"},
            "openid-connect": {
                "config.issuer": spec["oidcIssuer"],
                "config.auth_methods[]": ["bearer"],
                "config.audience_required[]": [spec["audience"]],
                "config.scopes_required[]": [expected["requiredScope"]],
                "config.bearer_token_param_type[]": ["header"],
                "config.verify_signature": "true",
                "config.verify_claims": "true",
                "config.ssl_verify": "true",
            },
        }
        for name, config in controls.items():
            current = by_name.get(name)
            if args.apply:
                # The quarantined host keeps the route unreachable while OIDC
                # is replaced, including if the operation is interrupted.
                if name == "openid-connect" and current:
                    if oidc_matches(current, expected, spec):
                        continue
                    request(args.admin_url, "DELETE", "/plugins/%s" % current["id"])
                    current = None
                endpoint = "/plugins/%s" % current["id"] if current else "/routes/%s/plugins" % route["id"]
                request(args.admin_url, "PATCH" if current else "POST", endpoint, {"name": name, "enabled": "true", **config})
        plugins = request(args.admin_url, "GET", "/routes/%s/plugins" % route["id"]).get("data", [])
        by_name = {plugin["name"]: plugin for plugin in plugins if plugin.get("enabled")}
        verify_plugins(by_name, expected, spec)
        if args.apply:
            request_json(args.admin_url, "PATCH", "/routes/%s" % route["id"], payload)
            route = singleton(args.admin_url, "routes", expected["name"])
            verify_route(route, expected, service["id"], spec["host"])
            remaining = request(args.admin_url, "GET", "/routes/%s/plugins" % route["id"]).get("data", [])
            for stale_deny in [plugin for plugin in remaining if plugin["name"] == "request-termination"]:
                request(args.admin_url, "DELETE", "/plugins/%s" % stale_deny["id"])
            remaining = request(args.admin_url, "GET", "/routes/%s/plugins" % route["id"]).get("data", [])
            if any(plugin["name"] == "request-termination" and plugin.get("enabled") for plugin in remaining):
                raise RuntimeError("callback deny plugin removal readback failed")
        evidence["routes"].append({
            "name": expected["name"], "service_id": service["id"],
            "route_id": route["id"], "hosts": route["hosts"],
            "paths": route["paths"], "methods": sorted(route["methods"]),
            "oidc": {"issuer": by_name["openid-connect"]["config"]["issuer"],
                     "audience_required": by_name["openid-connect"]["config"]["audience_required"],
                     "scopes_required": by_name["openid-connect"]["config"]["scopes_required"],
                     "anonymous": by_name["openid-connect"]["config"].get("anonymous")},
        })
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print("KONG_CALLBACK_ROUTES=%s" % ("APPLIED" if args.apply else "PASS"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
