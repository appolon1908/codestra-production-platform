#!/usr/bin/env python3
"""Fail-closed validator for the Codestra integration constitution."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import yaml


SYSTEM_FIELDS = {
    "class", "owner", "host", "private_address", "public_address",
    "business_role", "data_owner", "interfaces", "database_owner",
    "allowed_callers", "allowed_targets",
}
CONNECTOR_FIELDS = {
    "connector_id", "source_system", "target_system", "direction", "protocol",
    "base_endpoint", "private_endpoint", "auth_method", "service_account",
    "required_scopes", "timeout_seconds", "retry_policy",
    "circuit_breaker_policy", "rate_limit_policy", "schema_version", "enabled",
    "environment", "business_owner", "technical_owner",
}
ENDPOINT_FIELDS = {
    "endpoint_id", "system", "method", "path", "version", "exposure",
    "auth_required", "service_account", "required_scope", "tenant_required",
    "campaign_required", "idempotency_required", "rate_limit",
    "request_schema", "response_schema", "owner", "status",
}
WEBHOOK_FIELDS = {
    "webhook_id", "sender", "receiver", "path", "authentication", "schema",
    "retry_policy", "idempotency", "owner", "dlq", "reconciliation", "enabled",
}


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


def require_fields(kind: str, identity: str, value: dict[str, Any], fields: set[str]) -> list[Finding]:
    missing = sorted(fields - value.keys())
    if not missing:
        return []
    return [Finding("critical", f"{kind}-schema", identity, f"missing fields: {', '.join(missing)}")]


def unique_ids(kind: str, values: list[dict[str, Any]], key: str) -> list[Finding]:
    seen: set[str] = set()
    findings: list[Finding] = []
    for item in values:
        identity = str(item.get(key, "<missing>"))
        if identity in seen:
            findings.append(Finding("critical", f"duplicate-{kind}", identity, "identifier is not unique"))
        seen.add(identity)
    return findings


def tracked_files(root: Path) -> Iterable[Path]:
    try:
        output = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        for item in output.decode().split("\0"):
            if item:
                yield root / item
    except (subprocess.CalledProcessError, FileNotFoundError):
        yield from (path for path in root.rglob("*") if path.is_file())


def source_scan(root: Path, policy: dict[str, Any]) -> list[Finding]:
    config = policy["source_scan"]
    extensions = set(config["extensions"])
    excluded = set(config["excluded_roots"])
    rules = [(rule, re.compile(rule["pattern"])) for rule in config["rules"]]
    secret_rules = [re.compile(pattern) for pattern in config.get("prohibited_secret_patterns", [])]
    findings: list[Finding] = []
    for path in tracked_files(root):
        relative = path.relative_to(root)
        if not path.is_file() or path.suffix not in extensions or relative.parts[0] in excluded:
            continue
        if relative.as_posix() in {"config/integration-policy.yaml", "config/integration-registries.yaml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for rule, pattern in rules:
            if any(relative.parts[: len(Path(prefix).parts)] == Path(prefix).parts for prefix in rule["source_roots"]):
                if match := pattern.search(text):
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append(Finding("critical", rule["id"], f"{relative}:{line}", "prohibited direct integration indicator"))
        for pattern in secret_rules:
            if match := pattern.search(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(Finding("critical", "plaintext-secret", f"{relative}:{line}", "credential-like literal"))
    return findings


def scan_n8n(root: Path, registries: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    approved_hosts = {"api.codestra.co", "codestra-middleware-integration-api-1", "codestra-n8n-internal-proxy"}
    for connector in registries["connectors"]:
        endpoint = str(connector["private_endpoint"]).split(":", 1)[0]
        approved_hosts.add(endpoint)
    for path in sorted((root / "n8n").rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            findings.append(Finding("critical", "n8n-json", str(path.relative_to(root)), str(error)))
            continue
        serialized = json.dumps(payload)
        if re.search(r'n8n-nodes-base\.(postgres|mysql|microsoftSql)', serialized, re.I):
            findings.append(Finding("critical", "n8n-database-direct", str(path.relative_to(root)), "database node is prohibited"))
        for url in re.findall(r'https?://([^/"}\\s]+)', serialized):
            host = url.split(":", 1)[0]
            if host not in approved_hosts and not host.endswith(".invalid"):
                findings.append(Finding("critical", "n8n-unregistered-destination", str(path.relative_to(root)), f"unregistered host: {host}"))
    return findings


def endpoint_discovery(root: Path, registries: dict[str, Any]) -> list[Finding]:
    registered = {(str(item["method"]).upper(), str(item["path"])) for item in registries["endpoints"]}
    discovered: set[tuple[str, str, str]] = set()
    openapi_path = root / "docs/openapi/control-plane-v1.yaml"
    if openapi_path.exists():
        spec = load_yaml(openapi_path)
        for path, operations in spec.get("paths", {}).items():
            for method in operations:
                if method.lower() in {"get", "post", "put", "patch", "delete"}:
                    discovered.add((method.upper(), path, str(openapi_path.relative_to(root))))
    kong_path = root / "deploy/kong/control-plane.yml"
    if kong_path.exists():
        kong = load_yaml(kong_path)
        for service in kong.get("services", []):
            for route in service.get("routes", []):
                for path in route.get("paths", []):
                    for method in route.get("methods", ["ANY"]):
                        discovered.add((str(method).upper(), str(path), str(kong_path.relative_to(root))))
    caddy_path = root / "operations/caddy/api.codestra.co.caddy"
    if caddy_path.exists():
        for line in caddy_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("@") and " path " in line:
                for path in line.split(" path ", 1)[1].split():
                    discovered.add(("GET", path, str(caddy_path.relative_to(root))))
    return [
        Finding("critical", "unregistered-public-endpoint", location, f"{method} {path}")
        for method, path, location in sorted(discovered)
        if (method, path) not in registered
    ]


def validate_runtime(snapshot_path: Path, policy: dict[str, Any]) -> list[Finding]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    findings: list[Finding] = []
    prohibited_ports = set(policy["runtime"]["prohibited_public_ports"])
    containers = snapshot.get("containers", [])
    for container in containers:
        name = container.get("name", "<unknown>")
        for binding in container.get("published_ports", []):
            if isinstance(binding, int):
                binding = {"container_port": binding, "host_ip": "0.0.0.0", "host_port": binding}
            if int(binding["container_port"]) in prohibited_ports and binding.get("host_ip") in {"", "0.0.0.0", "::"}:
                findings.append(Finding("critical", "private-port-published", name, f"port {binding['container_port']} must remain private"))
        for destination in container.get("outbound_destinations", []):
            if destination.get("registered") is not True:
                findings.append(Finding("critical", "unknown-runtime-destination", name, str(destination.get("destination"))))
        if container.get("unknown_service_accounts"):
            findings.append(Finding("critical", "unknown-service-account", name, "runtime uses an unregistered service identity"))
    for endpoint in snapshot.get("public_endpoints", []):
        if endpoint.get("registered") is not True:
            findings.append(Finding("critical", "unregistered-public-endpoint", str(endpoint.get("path")), "public endpoint absent from registry"))
    for boundary in policy["runtime"].get("database_boundaries", []):
        database_pattern = re.compile(boundary["container_pattern"])
        allowed_patterns = [re.compile(pattern) for pattern in boundary["allowed_peer_patterns"]]
        for database in (item for item in containers if database_pattern.search(item.get("name", ""))):
            database_networks = set(database.get("networks", []))
            for peer in containers:
                if peer is database or not database_networks.intersection(peer.get("networks", [])):
                    continue
                if not any(pattern.search(peer.get("name", "")) for pattern in allowed_patterns):
                    findings.append(Finding("critical", "cross-application-db-network", database["name"], f"unapproved network peer: {peer.get('name')}"))
    return findings


def validate(root: Path, policy: dict[str, Any], registries: dict[str, Any], runtime: Path | None) -> list[Finding]:
    findings: list[Finding] = []
    if policy.get("default_decision") != "deny":
        findings.append(Finding("critical", "default-deny", "integration-policy.yaml", "default_decision must be deny"))
    if policy.get("exceptions"):
        required = {"reason", "owner", "systems", "scope", "expires_at", "security_review", "rollback_plan", "approval"}
        for index, exception in enumerate(policy["exceptions"]):
            findings += require_fields("exception", str(index), exception, required)
    systems = policy.get("systems", {})
    for name, system in systems.items():
        findings += require_fields("system", name, system, SYSTEM_FIELDS)
        for target in system.get("allowed_targets", []):
            if target in set(system.get("forbidden_targets", [])):
                findings.append(Finding("critical", "conflicting-path", name, f"{target} is both allowed and forbidden"))
    connectors = registries.get("connectors", [])
    endpoints = registries.get("endpoints", [])
    webhooks = registries.get("webhooks", [])
    findings += unique_ids("connector", connectors, "connector_id")
    findings += unique_ids("endpoint", endpoints, "endpoint_id")
    findings += unique_ids("webhook", webhooks, "webhook_id")
    for item in connectors:
        identity = str(item.get("connector_id", "<missing>"))
        findings += require_fields("connector", identity, item, CONNECTOR_FIELDS)
        if item.get("source_system") not in systems or item.get("target_system") not in systems:
            findings.append(Finding("critical", "connector-system", identity, "source or target is unregistered"))
        if not isinstance(item.get("timeout_seconds"), int) or item.get("timeout_seconds", 0) <= 0:
            findings.append(Finding("critical", "connector-timeout", identity, "positive timeout is required"))
        if str(item.get("auth_method", "")).lower() in {"none", "plaintext"}:
            findings.append(Finding("critical", "connector-auth", identity, "authenticated secret-free reference required"))
    for item in endpoints:
        identity = str(item.get("endpoint_id", "<missing>"))
        findings += require_fields("endpoint", identity, item, ENDPOINT_FIELDS)
        if item.get("method") in {"POST", "PUT", "PATCH", "DELETE"} and item.get("exposure") != "public_health":
            if not item.get("auth_required"):
                findings.append(Finding("critical", "endpoint-auth", identity, "mutating endpoint must authenticate"))
    for item in webhooks:
        identity = str(item.get("webhook_id", "<missing>"))
        findings += require_fields("webhook", identity, item, WEBHOOK_FIELDS)
        if item.get("authentication") in {None, "none"} or not item.get("idempotency"):
            findings.append(Finding("critical", "webhook-security", identity, "authentication and idempotency are mandatory"))
    findings += source_scan(root, policy)
    findings += scan_n8n(root, registries)
    findings += endpoint_discovery(root, registries)
    if runtime:
        findings += validate_runtime(runtime, policy)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--registries", type=Path)
    parser.add_argument("--runtime-snapshot", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    policy_path = args.policy or root / "config/integration-policy.yaml"
    registries_path = args.registries or root / "config/integration-registries.yaml"
    findings = validate(root, load_yaml(policy_path), load_yaml(registries_path), args.runtime_snapshot)
    payload = {
        "schema": "codestra.integration-architecture-check.v1",
        "status": "PASS" if not findings else "FAIL",
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "registries_sha256": hashlib.sha256(registries_path.read_bytes()).hexdigest(),
        "critical_findings": len(findings),
        "findings": [asdict(item) for item in findings],
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
