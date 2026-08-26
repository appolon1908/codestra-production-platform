#!/usr/bin/env python3
"""Reconcile control-plane implementation, OpenAPI, Kong, and endpoint registry coverage."""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


REQUIRED_FIELDS = {
    "endpoint_id",
    "methods",
    "path",
    "implementation_tokens",
    "exposure",
    "auth",
    "scope",
    "tenant_required",
    "idempotency",
    "openapi",
    "kong",
    "registry",
    "lifecycle",
    "owner",
}
COVERAGE_VALUES = {"present", "gap", "not_required"}
EXPOSURES = {"public_api", "public_health", "private_api", "private_health"}
LIFECYCLES = {"active", "source_ready", "staging", "planned", "deprecated"}
IDEMPOTENCY = {"required", "not_required", "exempt"}
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
HTTP_METHODS = MUTATING_METHODS | {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    location: str
    message: str


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return value


def unique(values: Iterable[dict[str, Any]], key: str, kind: str) -> list[Finding]:
    seen: set[str] = set()
    findings: list[Finding] = []
    for row in values:
        identity = str(row.get(key, "<missing>"))
        if identity in seen:
            findings.append(Finding("critical", f"duplicate-{kind}", identity, "identifier is not unique"))
        seen.add(identity)
    return findings


def _string_values(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        values: set[str] = set()
        for item in node.elts:
            values.update(_string_values(item))
        return values
    return set()


def _path_expression(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "path"


def implementation_route_fragments(source: str) -> set[str]:
    """Extract route literals used in request-path comparisons and prefix/suffix tests."""
    tree = ast.parse(source)
    fragments: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and _path_expression(node.left):
            for comparator in node.comparators:
                fragments.update(value for value in _string_values(comparator) if value.startswith("/"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in {"startswith", "endswith"} or not _path_expression(node.func.value):
                continue
            for argument in node.args:
                fragments.update(value for value in _string_values(argument) if value.startswith("/"))
    return fragments


def openapi_operations(spec: dict[str, Any]) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for path, value in spec.get("paths", {}).items():
        if not isinstance(value, dict):
            continue
        for method in value:
            upper = str(method).upper()
            if upper in HTTP_METHODS:
                operations.add((upper, str(path)))
    return operations


def registry_operations(registry: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(row.get("method", "")).upper(), str(row.get("path", "")))
        for row in registry.get("endpoints", [])
    }


def kong_routes(kong: dict[str, Any]) -> list[tuple[set[str], str]]:
    routes: list[tuple[set[str], str]] = []
    for service in kong.get("services", []):
        for route in service.get("routes", []):
            methods = {str(value).upper() for value in route.get("methods", [])}
            for path in route.get("paths", []):
                routes.append((methods, str(path).rstrip("/") or "/"))
    return routes


def kong_covers(routes: list[tuple[set[str], str]], method: str, path: str) -> bool:
    for methods, prefix in routes:
        if methods and method not in methods:
            continue
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _token_fragment(token: str) -> str:
    return token.strip().strip("'\"")


def _fragment_covered(fragment: str, endpoints: list[dict[str, Any]]) -> bool:
    for row in endpoints:
        path = str(row.get("path", ""))
        tokens = {_token_fragment(str(value)) for value in row.get("implementation_tokens", [])}
        if fragment in tokens or path == fragment or path.startswith(fragment) or path.endswith(fragment):
            return True
    return False


def validate(root: Path, manifest: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if manifest.get("version") != 1:
        findings.append(Finding("critical", "manifest-version", "config/control-plane-api-surface.yaml", "version must be 1"))

    endpoints = manifest.get("endpoints", [])
    if not isinstance(endpoints, list):
        return findings + [Finding("critical", "manifest-schema", "endpoints", "must be a list")]
    findings += unique(endpoints, "endpoint_id", "endpoint")

    source_path = root / str(manifest.get("implementation", ""))
    openapi_path = root / str(manifest.get("openapi", ""))
    kong_path = root / str(manifest.get("kong", ""))
    registry_path = root / str(manifest.get("registry", ""))
    for name, path in (
        ("implementation", source_path),
        ("openapi", openapi_path),
        ("kong", kong_path),
        ("registry", registry_path),
    ):
        if not path.is_file():
            findings.append(Finding("critical", "missing-source", name, str(path.relative_to(root))))
    if findings:
        return findings

    source = source_path.read_text(encoding="utf-8")
    openapi = openapi_operations(load_yaml(openapi_path))
    registry = registry_operations(load_yaml(registry_path))
    routes = kong_routes(load_yaml(kong_path))
    route_keys: set[tuple[str, str]] = set()

    for row in endpoints:
        identity = str(row.get("endpoint_id", "<missing>"))
        missing = sorted(REQUIRED_FIELDS - set(row))
        if missing:
            findings.append(Finding("critical", "endpoint-schema", identity, f"missing fields: {', '.join(missing)}"))
            continue
        methods = [str(value).upper() for value in row["methods"]]
        path = str(row["path"])
        if not methods or any(method not in HTTP_METHODS for method in methods):
            findings.append(Finding("critical", "endpoint-method", identity, repr(methods)))
        if not path.startswith("/"):
            findings.append(Finding("critical", "endpoint-path", identity, path))
        for method in methods:
            key = (method, path)
            if key in route_keys:
                findings.append(Finding("critical", "duplicate-route", identity, f"{method} {path}"))
            route_keys.add(key)
        if row["exposure"] not in EXPOSURES:
            findings.append(Finding("critical", "endpoint-exposure", identity, str(row["exposure"])))
        if row["lifecycle"] not in LIFECYCLES:
            findings.append(Finding("critical", "endpoint-lifecycle", identity, str(row["lifecycle"])))
        if row["idempotency"] not in IDEMPOTENCY:
            findings.append(Finding("critical", "endpoint-idempotency", identity, str(row["idempotency"])))
        if MUTATING_METHODS.intersection(methods) and row["idempotency"] == "not_required":
            findings.append(Finding("critical", "mutation-idempotency", identity, "mutation requires idempotency or an exemption"))
        if row["idempotency"] == "exempt" and not row.get("idempotency_exemption"):
            findings.append(Finding("critical", "idempotency-exemption", identity, "exemption reason is required"))
        if row["exposure"] == "public_api" and row["kong"] == "not_required":
            findings.append(Finding("critical", "public-api-bypass", identity, "public business API cannot bypass Kong"))
        for layer in ("openapi", "kong", "registry"):
            status = row[layer]
            if status not in COVERAGE_VALUES:
                findings.append(Finding("critical", "coverage-status", identity, f"{layer}={status}"))
            if status == "gap" and not str(row.get("remediation", "")).strip():
                findings.append(Finding("critical", "gap-remediation", identity, f"{layer} gap needs remediation"))
        for token in row["implementation_tokens"]:
            if str(token) not in source:
                findings.append(Finding("critical", "implementation-token", identity, f"missing token: {token}"))
        for method in methods:
            if row["openapi"] == "present" and (method, path) not in openapi:
                findings.append(Finding("critical", "openapi-drift", identity, f"missing {method} {path}"))
            if row["registry"] == "present" and (method, path) not in registry:
                findings.append(Finding("critical", "registry-drift", identity, f"missing {method} {path}"))
            if row["kong"] == "present" and not kong_covers(routes, method, path):
                findings.append(Finding("critical", "kong-drift", identity, f"missing route for {method} {path}"))

    for fragment in sorted(implementation_route_fragments(source)):
        if not _fragment_covered(fragment, endpoints):
            findings.append(Finding("critical", "unregistered-implementation-route", fragment, "request-path literal is absent from the API surface inventory"))
    return findings


def coverage_gaps(manifest: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for row in manifest.get("endpoints", []):
        for layer in ("openapi", "kong", "registry"):
            if row.get(layer) == "gap":
                findings.append(Finding("high", f"{layer}-coverage-gap", str(row["endpoint_id"]), str(row.get("remediation", ""))))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--strict", action="store_true", help="Fail while any declared coverage gap remains")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = args.manifest or root / "config/control-plane-api-surface.yaml"
    manifest = load_yaml(manifest_path)
    structural = validate(root, manifest)
    gaps = coverage_gaps(manifest)
    findings = structural + (gaps if args.strict and not structural else [])
    payload = {
        "manifest": str(manifest_path.relative_to(root)),
        "endpoints": len(manifest.get("endpoints", [])),
        "coverage_gaps": len(gaps),
        "strict": args.strict,
        "status": "PASS" if not findings else "FAIL",
        "findings": [asdict(item) for item in findings],
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"CONTROL_PLANE_API_SURFACE={payload['status']} ENDPOINTS={payload['endpoints']} COVERAGE_GAPS={payload['coverage_gaps']} STRICT={int(args.strict)}")
        for item in findings:
            print(f"{item.severity.upper()} {item.rule} {item.location}: {item.message}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
