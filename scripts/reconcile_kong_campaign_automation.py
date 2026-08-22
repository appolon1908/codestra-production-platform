#!/usr/bin/env python3
"""Reconcile exact JWT-protected campaign automation routes in Kong."""

from __future__ import annotations

import argparse
import base64
import json
import textwrap
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request(base: str, method: str, path: str, payload=None):
    data = None if payload is None else urlencode(payload, doseq=True).encode()
    with urlopen(Request(base.rstrip("/") + path, method=method, data=data), timeout=15) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def _der_length(length: int) -> bytes:
    if length < 128:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _der(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_length(len(value)) + value


def _integer(value: int) -> bytes:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big") or b"\0"
    if raw[0] & 0x80:
        raw = b"\0" + raw
    return _der(0x02, raw)


def rsa_public_key_pem(jwk: dict[str, str]) -> str:
    """Build an RFC 5280 SubjectPublicKeyInfo PEM from an RSA JWK."""
    decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    modulus = int.from_bytes(decode(jwk["n"]), "big")
    exponent = int.from_bytes(decode(jwk["e"]), "big")
    rsa_key = _der(0x30, _integer(modulus) + _integer(exponent))
    algorithm = bytes.fromhex("300d06092a864886f70d0101010500")
    subject = _der(0x30, algorithm + _der(0x03, b"\0" + rsa_key))
    encoded = base64.b64encode(subject).decode()
    lines = "\n".join(textwrap.wrap(encoded, 64))
    return f"-----BEGIN PUBLIC KEY-----\n{lines}\n-----END PUBLIC KEY-----\n"


def active_rsa_key(jwks_url: str) -> dict[str, str]:
    with urlopen(jwks_url, timeout=15) as response:
        keys = json.load(response).get("keys", [])
    candidates = [
        key for key in keys
        if key.get("kty") == "RSA" and key.get("alg") == "RS256" and key.get("use") == "sig"
    ]
    if len(candidates) != 1:
        raise RuntimeError("exactly one active Keycloak RS256 signing key is required")
    return candidates[0]


def claim_guard(manifest: dict, required_scope: str) -> str:
    issuer = json.dumps(manifest["issuer"])
    audience = json.dumps(manifest["audience"])
    environment = json.dumps(manifest["environment"])
    client = json.dumps(manifest["consumer"]["custom_id"])
    scope = json.dumps(required_scope)
    return (
        "local h=kong.request.get_header('authorization') or '';"
        "local t=h:match('[Bb]earer%s+(.+)') or '';"
        "local p=t:match('^[^.]+%.([^.]+)%.') or '';"
        "p=p:gsub('-','+'):gsub('_','/');p=p..string.rep('=',(4-#p%4)%4);"
        "local raw=ngx.decode_base64(p);local c=raw and require('cjson.safe').decode(raw) or {};"
        "local s={};for x in string.gmatch(c.scope or '','%S+') do s[x]=true end;"
        f"if c.iss~={issuer} then return kong.response.exit(401,{{error='invalid_issuer'}}) end;"
        f"if c.azp~={client} or c.environment~={environment} then "
        "return kong.response.exit(403,{error='service_identity_denied'}) end;"
        f"local a=c.aud;local ok=a=={audience};"
        f"if type(a)=='table' then for _,v in ipairs(a) do if v=={audience} then ok=true end end end;"
        "if not ok then return kong.response.exit(401,{error='invalid_audience'}) end;"
        f"if not s[{scope}] then return kong.response.exit(403,{{error='insufficient_scope'}}) end"
    )


def one(items: list[dict], description: str) -> dict | None:
    if len(items) > 1:
        raise RuntimeError(f"ambiguous {description}")
    return items[0] if items else None


def ensure_entity(admin: str, collection: str, query: str, payload: dict, apply: bool) -> dict:
    existing = one(request(admin, "GET", f"/{collection}?" + urlencode({"name": query}))["data"], query)
    if existing:
        if apply:
            request(admin, "PATCH", f"/{collection}/{existing['id']}", payload)
        return existing
    if not apply:
        raise RuntimeError(f"missing {collection}: {query}")
    return request(admin, "POST", f"/{collection}", payload)


def ensure_plugin(admin: str, route_id: str, name: str, payload: dict, apply: bool) -> None:
    plugins = request(admin, "GET", f"/routes/{route_id}/plugins")["data"]
    existing = one([item for item in plugins if item["name"] == name and item.get("enabled")], name)
    if existing:
        if apply:
            request(admin, "PATCH", f"/plugins/{existing['id']}", payload)
        return
    if not apply:
        raise RuntimeError(f"missing route plugin: {name}")
    request(admin, "POST", f"/routes/{route_id}/plugins", {"name": name, **payload})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--jwks-url", required=True)
    parser.add_argument("--manifest", type=Path, default=Path("config/kong-campaign-automation-routes.json"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    public_key = rsa_public_key_pem(active_rsa_key(args.jwks_url))
    service = ensure_entity(args.admin_url, "services", manifest["service"]["name"], manifest["service"], args.apply)
    consumers = request(args.admin_url, "GET", "/consumers?size=1000")["data"]
    consumer = one([row for row in consumers if row.get("username") == manifest["consumer"]["username"]], "consumer")
    if not consumer:
        if not args.apply:
            raise RuntimeError("campaign service consumer is missing")
        consumer = request(args.admin_url, "POST", "/consumers", manifest["consumer"])
    credentials = request(args.admin_url, "GET", f"/consumers/{consumer['id']}/jwt")["data"]
    credential = one([row for row in credentials if row.get("key") == manifest["consumer"]["custom_id"]], "JWT credential")
    jwt_payload = {"key": manifest["consumer"]["custom_id"], "algorithm": "RS256", "rsa_public_key": public_key}
    if credential and args.apply:
        request(
            args.admin_url,
            "PATCH",
            f"/consumers/{consumer['id']}/jwt/{credential['id']}",
            jwt_payload,
        )
    elif not credential and args.apply:
        request(args.admin_url, "POST", f"/consumers/{consumer['id']}/jwt", jwt_payload)
    elif not credential:
        raise RuntimeError("campaign JWT credential is missing")
    evidence = []
    for expected in manifest["routes"]:
        routes = request(args.admin_url, "GET", "/routes?" + urlencode({"name": expected["name"]}))["data"]
        route = one(routes, expected["name"])
        route_payload = {
            "name": expected["name"], "service.id": service["id"],
            "hosts[]": [manifest["host"]], "paths[]": [expected["path"]],
            "methods[]": ["POST"], "protocols[]": ["https"],
            "strip_path": "false", "https_redirect_status_code": 426,
        }
        if route and args.apply:
            route = request(args.admin_url, "PATCH", f"/routes/{route['id']}", route_payload)
        elif not route and args.apply:
            route = request(args.admin_url, "POST", "/routes", route_payload)
        elif not route:
            raise RuntimeError(f"missing route: {expected['name']}")
        ensure_plugin(args.admin_url, route["id"], "jwt", {
            "config.key_claim_name": "azp", "config.claims_to_verify[]": ["exp"],
            "config.header_names[]": ["authorization"], "config.run_on_preflight": "true",
        }, args.apply)
        ensure_plugin(args.admin_url, route["id"], "post-function", {
            "config.access[]": [claim_guard(manifest, expected["scope"])],
        }, args.apply)
        ensure_plugin(args.admin_url, route["id"], "request-size-limiting", {
            "config.allowed_payload_size": expected["max_body_mb"],
        }, args.apply)
        ensure_plugin(args.admin_url, route["id"], "rate-limiting", {
            "config.minute": expected["rate_per_minute"], "config.policy": "local",
            "config.limit_by": "consumer",
        }, args.apply)
        ensure_plugin(args.admin_url, route["id"], "correlation-id", {
            "config.header_name": "X-Correlation-ID", "config.generator": "uuid",
            "config.echo_downstream": "true",
        }, args.apply)
        evidence.append({
            "route": expected["path"], "scope": expected["scope"],
            "audience": manifest["audience"], "issuer": manifest["issuer"],
            "jwt_signature": "RS256", "status": "PASS",
        })
    args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print("KONG_CAMPAIGN_AUTOMATION_ROUTES=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
