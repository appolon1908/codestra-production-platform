#!/usr/bin/env python3
"""Reconcile control-plane implementation, OpenAPI, Kong, registry, and assurance coverage."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
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
DEFAULT_ASSURANCE = Path("config/control-plane-api-assurance.yaml")
ASSURANCE_ENDPOINT_FIELDS = {"handler", "tokens", "idempotency", "gateway_auth"}
IDEMPOTENCY_ASSURANCE_FIELDS = {
    "status",
    "implementation_tokens",
    "test_path",
    "test_tokens",
    "remediation",
}
GATEWAY_AUTH_ASSURANCE_FIELDS = {
    "status",
    "remediation",
    "config_path",
    "config_tokens",
    "test_path",
    "test_tokens",
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


def load_assurance(root: Path, path: Path | None = None) -> dict[str, Any]:
    assurance_path = path or root / DEFAULT_ASSURANCE
    if not assurance_path.is_file():
        return {"version": 1, "handlers": {}, "endpoints": {}}
    return load_yaml(assurance_path)


def unique(values: Iterable[dict[str, Any]], key: str, kind: str) -> list[Finding]:
    seen: set[str] = set()
    findings: list[Finding] = []
    for row in values:
        identity = str(row.get(key, "<missing>"))
        if identity in seen:
            findings.append(
                Finding("critical", f"duplicate-{kind}", identity, "identifier is not unique")
            )
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


def implementation_handler_sources(source: str) -> dict[str, str]:
    """Return exact function/method source segments keyed by function name."""
    tree = ast.parse(source)
    handlers: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        segment = ast.get_source_segment(source, node)
        if segment is not None:
            handlers[node.name] = segment
    return handlers


def implementation_route_fragments(source: str) -> dict[str, set[str]]:
    """Extract request-path predicates separately for every handler/helper method."""
    tree = ast.parse(source)
    fragments: dict[str, set[str]] = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        values: set[str] = set()
        for node in ast.walk(function):
            if isinstance(node, ast.Compare) and _path_expression(node.left):
                for comparator in node.comparators:
                    values.update(
                        value for value in _string_values(comparator) if value.startswith("/")
                    )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr not in {"startswith", "endswith"}
                    or not _path_expression(node.func.value)
                ):
                    continue
                for argument in node.args:
                    values.update(
                        value for value in _string_values(argument) if value.startswith("/")
                    )
        if values:
            fragments[function.name] = values
    return fragments


def route_predicate_groups(source: str) -> list[set[str]]:
    """Return path literals that must participate in the same branch predicate."""
    def alternatives(node: ast.AST) -> list[set[str]]:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return [group for value in node.values for group in alternatives(value)]
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            combined = [set()]
            for value in node.values:
                combined = [left | right for left in combined for right in alternatives(value)]
            return combined
        values = {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and child.value.startswith("/")
        }
        return [values]

    tree = ast.parse(source)
    groups: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        groups.extend(group for group in alternatives(node.test) if group)
    return groups


def endpoint_route_predicate_covered(
    handler_source: str,
    implementation_tokens: list[str],
) -> bool:
    fragments = {
        _token_fragment(token)
        for token in implementation_tokens
        if _token_fragment(token).startswith("/")
    }
    if len(fragments) < 2:
        return True
    return any(fragments.issubset(group) for group in route_predicate_groups(handler_source))


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


def _handler_methods(name: str, assurance: dict[str, Any]) -> set[str]:
    if name.startswith("do_"):
        return {name.removeprefix("do_").upper()}
    configured = assurance.get("handlers", {}).get(name, [])
    return {str(value).upper() for value in configured}


def delegated_handler_called(
    name: str,
    methods: set[str],
    handler_sources: dict[str, str],
) -> bool:
    if name.startswith("do_"):
        return True
    call = f"self.{name}("
    return all(call in handler_sources.get(f"do_{method}", "") for method in methods)


def _endpoint_handler(
    row: dict[str, Any],
    assurance_entry: dict[str, Any],
) -> str:
    explicit = str(assurance_entry.get("handler", "")).strip()
    if explicit:
        return explicit
    methods = [str(value).upper() for value in row.get("methods", [])]
    if len(methods) == 1:
        return f"do_{methods[0]}"
    return ""


def _fragment_covered(
    fragment: str,
    endpoints: list[dict[str, Any]],
    allowed_methods: set[str],
) -> bool:
    for row in endpoints:
        methods = {str(value).upper() for value in row.get("methods", [])}
        if allowed_methods and not methods.intersection(allowed_methods):
            continue
        path = str(row.get("path", ""))
        tokens = {_token_fragment(str(value)) for value in row.get("implementation_tokens", [])}
        if fragment in tokens or path == fragment or path.startswith(fragment) or path.endswith(fragment):
            return True
    return False


def _assurance_entries(assurance: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = assurance.get("endpoints", {})
    if not isinstance(value, dict):
        return {}
    return {
        str(endpoint_id): row
        for endpoint_id, row in value.items()
        if isinstance(row, dict)
    }


def _gap_remediation(row: dict[str, Any], evidence: dict[str, Any]) -> str:
    return str(evidence.get("remediation") or row.get("remediation") or "").strip()


def _repository_token_proof(
    root: Path,
    path_value: object,
    tokens_value: object,
) -> bool:
    if not isinstance(path_value, str) or not path_value.strip():
        return False
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        return False
    candidate = (root / path).resolve()
    repository_root = root.resolve()
    if not candidate.is_relative_to(repository_root) or not candidate.is_file():
        return False
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", str(path)],
        cwd=repository_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False,
    )
    if tracked.returncode != 0:
        return False
    if (
        not isinstance(tokens_value, list)
        or not tokens_value
        or any(not isinstance(token, str) or not token for token in tokens_value)
    ):
        return False
    source = candidate.read_text(encoding="utf-8")
    return all(token in source for token in tokens_value)


def _gateway_route_proof(
    root: Path,
    row: dict[str, Any],
    evidence: dict[str, Any],
) -> bool:
    """Bind configuration and behavior evidence to this exact public route."""
    methods = {str(value).upper() for value in row.get("methods", [])}
    path = str(row.get("path", ""))
    scope = str(row.get("scope", ""))
    config_path = evidence.get("config_path")
    if not _repository_token_proof(root, config_path, evidence.get("config_tokens")):
        return False
    try:
        kong = load_yaml(root / str(config_path))
    except (OSError, UnicodeError, yaml.YAMLError, ValueError):
        return False
    routes = kong_routes(kong)
    if not methods or not all(kong_covers(routes, method, path) for method in methods):
        return False
    config_source = (root / str(config_path)).read_text(encoding="utf-8")
    if scope and scope not in {"none", "not_required"} and scope not in config_source:
        return False
    return True


def _gateway_behavior_proof(
    root: Path,
    row: dict[str, Any],
    evidence: dict[str, Any],
) -> bool:
    """Require route-specific allow and authentication-deny assertions."""
    test_path = evidence.get("test_path")
    if not _repository_token_proof(root, test_path, evidence.get("test_tokens")):
        return False
    source = (root / str(test_path)).read_text(encoding="utf-8")
    path = str(row.get("path", ""))
    methods = {str(value).upper() for value in row.get("methods", [])}
    has_deny = any(token in source for token in ("401", "403", "unauthorized", "forbidden"))
    has_allow = any(token in source for token in ("200", "201", "202", "204", "success"))
    return path in source and all(method in source for method in methods) and has_deny and has_allow


def validate(
    root: Path,
    manifest: dict[str, Any],
    assurance: dict[str, Any] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    assurance = assurance if assurance is not None else load_assurance(root)
    if manifest.get("version") != 1:
        findings.append(
            Finding(
                "critical",
                "manifest-version",
                "config/control-plane-api-surface.yaml",
                "version must be 1",
            )
        )
    if assurance.get("version") != 1:
        findings.append(
            Finding(
                "critical",
                "assurance-version",
                str(DEFAULT_ASSURANCE),
                "version must be 1",
            )
        )

    endpoints = manifest.get("endpoints", [])
    if not isinstance(endpoints, list):
        return findings + [Finding("critical", "manifest-schema", "endpoints", "must be a list")]
    findings += unique(endpoints, "endpoint_id", "endpoint")
    endpoint_ids = {str(row.get("endpoint_id", "")) for row in endpoints}

    raw_assurance_entries = assurance.get("endpoints", {})
    if not isinstance(raw_assurance_entries, dict):
        findings.append(
            Finding("critical", "assurance-schema", "endpoints", "must be a mapping")
        )
        raw_assurance_entries = {}
    assurance_entries = _assurance_entries(assurance)
    for endpoint_id, entry in raw_assurance_entries.items():
        identity = str(endpoint_id)
        if identity not in endpoint_ids:
            findings.append(
                Finding("critical", "unknown-assurance-endpoint", identity, "not present in API surface")
            )
        if not isinstance(entry, dict):
            findings.append(
                Finding("critical", "assurance-entry-schema", identity, "must be a mapping")
            )
            continue
        unexpected = sorted(set(entry) - ASSURANCE_ENDPOINT_FIELDS)
        if unexpected:
            findings.append(
                Finding(
                    "critical",
                    "assurance-entry-schema",
                    identity,
                    f"unexpected fields: {', '.join(unexpected)}",
                )
            )

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
            findings.append(
                Finding("critical", "missing-source", name, str(path.relative_to(root)))
            )
    if findings:
        return findings

    source = source_path.read_text(encoding="utf-8")
    handler_sources = implementation_handler_sources(source)
    openapi = openapi_operations(load_yaml(openapi_path))
    registry = registry_operations(load_yaml(registry_path))
    routes = kong_routes(load_yaml(kong_path))
    route_keys: set[tuple[str, str]] = set()

    for row in endpoints:
        identity = str(row.get("endpoint_id", "<missing>"))
        evidence = assurance_entries.get(identity, {})
        missing = sorted(REQUIRED_FIELDS - set(row))
        if missing:
            findings.append(
                Finding(
                    "critical",
                    "endpoint-schema",
                    identity,
                    f"missing fields: {', '.join(missing)}",
                )
            )
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
                findings.append(
                    Finding("critical", "duplicate-route", identity, f"{method} {path}")
                )
            route_keys.add(key)
        if row["exposure"] not in EXPOSURES:
            findings.append(
                Finding("critical", "endpoint-exposure", identity, str(row["exposure"]))
            )
        if row["lifecycle"] not in LIFECYCLES:
            findings.append(
                Finding("critical", "endpoint-lifecycle", identity, str(row["lifecycle"]))
            )
        if row["idempotency"] not in IDEMPOTENCY:
            findings.append(
                Finding("critical", "endpoint-idempotency", identity, str(row["idempotency"]))
            )
        if MUTATING_METHODS.intersection(methods) and row["idempotency"] == "not_required":
            findings.append(
                Finding(
                    "critical",
                    "mutation-idempotency",
                    identity,
                    "mutation requires idempotency or an exemption",
                )
            )
        if row["idempotency"] == "exempt" and not row.get("idempotency_exemption"):
            findings.append(
                Finding(
                    "critical",
                    "idempotency-exemption",
                    identity,
                    "exemption reason is required",
                )
            )
        if row["exposure"] == "public_api" and row["kong"] == "not_required":
            findings.append(
                Finding(
                    "critical",
                    "public-api-bypass",
                    identity,
                    "public business API cannot bypass Kong",
                )
            )
        for layer in ("openapi", "kong", "registry"):
            status = row[layer]
            if status not in COVERAGE_VALUES:
                findings.append(
                    Finding("critical", "coverage-status", identity, f"{layer}={status}")
                )
            if status == "gap" and not str(row.get("remediation", "")).strip():
                findings.append(
                    Finding(
                        "critical",
                        "gap-remediation",
                        identity,
                        f"{layer} gap needs remediation",
                    )
                )

        handler = _endpoint_handler(row, evidence)
        handler_text = handler_sources.get(handler, "")
        if not handler:
            findings.append(
                Finding(
                    "critical",
                    "implementation-handler",
                    identity,
                    "multi-method endpoints require an explicit assurance handler",
                )
            )
        elif not handler_text:
            findings.append(
                Finding("critical", "implementation-handler", identity, f"missing handler: {handler}")
            )
        else:
            allowed = _handler_methods(handler, assurance)
            if not allowed or not set(methods).issubset(allowed):
                findings.append(
                    Finding(
                        "critical",
                        "implementation-method-binding",
                        identity,
                        f"{handler} does not prove methods {methods}; allowed={sorted(allowed)}",
                    )
                )
            if not delegated_handler_called(handler, set(methods), handler_sources):
                findings.append(Finding(
                    "critical",
                    "implementation-delegation-binding",
                    identity,
                    f"HTTP dispatchers do not call delegated handler {handler}",
                ))
            implementation_tokens = [
                str(value)
                for value in row["implementation_tokens"]
            ] + [str(value) for value in evidence.get("tokens", [])]
            for token in implementation_tokens:
                if token not in handler_text:
                    findings.append(
                        Finding(
                            "critical",
                            "implementation-token",
                            identity,
                            f"missing from {handler}: {token}",
                        )
                    )
            if not endpoint_route_predicate_covered(handler_text, implementation_tokens):
                findings.append(
                    Finding(
                        "critical",
                        "implementation-route-predicate",
                        identity,
                        f"path fragments are not bound in one {handler} branch predicate",
                    )
                )

        idempotency_evidence = evidence.get("idempotency", {})
        if idempotency_evidence and not isinstance(idempotency_evidence, dict):
            findings.append(
                Finding("critical", "idempotency-assurance-schema", identity, "must be a mapping")
            )
            idempotency_evidence = {}
        if isinstance(idempotency_evidence, dict):
            unexpected = sorted(set(idempotency_evidence) - IDEMPOTENCY_ASSURANCE_FIELDS)
            if unexpected:
                findings.append(
                    Finding(
                        "critical",
                        "idempotency-assurance-schema",
                        identity,
                        f"unexpected fields: {', '.join(unexpected)}",
                    )
                )
        if row["idempotency"] == "required":
            status = str(idempotency_evidence.get("status", "gap"))
            if status not in {"present", "gap"}:
                findings.append(
                    Finding(
                        "critical",
                        "idempotency-assurance-status",
                        identity,
                        f"required endpoint cannot use status={status}",
                    )
                )
            if status == "present":
                raw_tokens = idempotency_evidence.get("implementation_tokens", [])
                tokens = raw_tokens if isinstance(raw_tokens, list) and all(
                    isinstance(value, str) and value for value in raw_tokens
                ) else []
                if not tokens:
                    findings.append(
                        Finding(
                            "critical",
                            "idempotency-proof",
                            identity,
                            "present assurance requires implementation tokens",
                        )
                    )
                for token in tokens:
                    if not handler_text or token not in handler_text:
                        findings.append(
                            Finding(
                                "critical",
                                "idempotency-token",
                                identity,
                                f"missing from {handler}: {token}",
                            )
                        )
                test_path_value = str(idempotency_evidence.get("test_path", "")).strip()
                raw_test_tokens = idempotency_evidence.get("test_tokens", [])
                test_tokens = raw_test_tokens if isinstance(raw_test_tokens, list) and all(
                    isinstance(value, str) and value for value in raw_test_tokens
                ) else []
                if not test_path_value or not test_tokens:
                    findings.append(
                        Finding(
                            "critical",
                            "idempotency-test-proof",
                            identity,
                            "present assurance requires a behavioral test path and tokens",
                        )
                    )
                else:
                    if not _repository_token_proof(root, test_path_value, test_tokens):
                        findings.append(
                            Finding(
                                "critical",
                                "idempotency-test-proof",
                                identity,
                                f"missing tracked behavioral test proof: {test_path_value}",
                            )
                        )
            elif not _gap_remediation(row, idempotency_evidence):
                findings.append(
                    Finding(
                        "critical",
                        "idempotency-gap-remediation",
                        identity,
                        "implementation gap requires remediation",
                    )
                )
        elif idempotency_evidence:
            status = str(idempotency_evidence.get("status", ""))
            if status not in {"", "not_required"}:
                findings.append(
                    Finding(
                        "critical",
                        "idempotency-assurance-status",
                        identity,
                        f"contract idempotency={row['idempotency']} conflicts with status={status}",
                    )
                )

        gateway_auth = evidence.get("gateway_auth", {})
        if row["exposure"] in {"public_api", "public_health"} and not gateway_auth:
            findings.append(Finding(
                "critical", "gateway-auth-assurance-missing", identity,
                "public routes require an explicit evidenced status or owned gap",
            ))
        if gateway_auth and not isinstance(gateway_auth, dict):
            findings.append(
                Finding("critical", "gateway-auth-assurance-schema", identity, "must be a mapping")
            )
            gateway_auth = {}
        if gateway_auth:
            unexpected = sorted(set(gateway_auth) - GATEWAY_AUTH_ASSURANCE_FIELDS)
            if unexpected:
                findings.append(
                    Finding(
                        "critical",
                        "gateway-auth-assurance-schema",
                        identity,
                        f"unexpected fields: {', '.join(unexpected)}",
                    )
                )
            status = str(gateway_auth.get("status", ""))
            if status not in COVERAGE_VALUES:
                findings.append(
                    Finding("critical", "gateway-auth-status", identity, status)
                )
            if status == "gap" and not _gap_remediation(row, gateway_auth):
                findings.append(
                    Finding(
                        "critical",
                        "gateway-auth-gap-remediation",
                        identity,
                        "authentication mismatch requires remediation",
                    )
                )
            if status in {"present", "not_required"}:
                if not _gateway_route_proof(root, row, gateway_auth):
                    findings.append(Finding(
                        "critical",
                        "gateway-auth-config-proof",
                        identity,
                        f"status={status} requires gateway configuration path and tokens",
                    ))
                if not _gateway_behavior_proof(root, row, gateway_auth):
                    findings.append(Finding(
                        "critical",
                        "gateway-auth-test-proof",
                        identity,
                        f"status={status} requires behavioral authentication test path and tokens",
                    ))
                if status == "not_required" and not _gap_remediation(row, gateway_auth):
                    findings.append(Finding(
                        "critical",
                        "gateway-auth-exemption",
                        identity,
                        "not_required authentication requires a documented rationale",
                    ))

        for method in methods:
            if row["openapi"] == "present" and (method, path) not in openapi:
                findings.append(
                    Finding("critical", "openapi-drift", identity, f"missing {method} {path}")
                )
            if row["registry"] == "present" and (method, path) not in registry:
                findings.append(
                    Finding("critical", "registry-drift", identity, f"missing {method} {path}")
                )
            if row["kong"] == "present" and not kong_covers(routes, method, path):
                findings.append(
                    Finding(
                        "critical",
                        "kong-drift",
                        identity,
                        f"missing route for {method} {path}",
                    )
                )

    for handler, fragments in implementation_route_fragments(source).items():
        allowed_methods = _handler_methods(handler, assurance)
        if not allowed_methods:
            continue
        for fragment in sorted(fragments):
            if not _fragment_covered(fragment, endpoints, allowed_methods):
                findings.append(
                    Finding(
                        "critical",
                        "unregistered-implementation-route",
                        f"{handler}:{fragment}",
                        "method-specific request-path predicate is absent from the API surface inventory",
                    )
                )
    return findings


def coverage_gaps(
    manifest: dict[str, Any],
    assurance: dict[str, Any] | None = None,
) -> list[Finding]:
    assurance = assurance or {"endpoints": {}}
    evidence_by_endpoint = _assurance_entries(assurance)
    findings: list[Finding] = []
    for row in manifest.get("endpoints", []):
        identity = str(row["endpoint_id"])
        evidence = evidence_by_endpoint.get(identity, {})
        for layer in ("openapi", "kong", "registry"):
            if row.get(layer) == "gap":
                findings.append(
                    Finding(
                        "high",
                        f"{layer}-coverage-gap",
                        identity,
                        str(row.get("remediation", "")),
                    )
                )
        if row.get("idempotency") == "required":
            idempotency = evidence.get("idempotency", {})
            status = idempotency.get("status", "gap") if isinstance(idempotency, dict) else "gap"
            if status == "gap":
                findings.append(
                    Finding(
                        "high",
                        "idempotency-implementation-gap",
                        identity,
                        _gap_remediation(row, idempotency if isinstance(idempotency, dict) else {}),
                    )
                )
        gateway_auth = evidence.get("gateway_auth", {})
        if isinstance(gateway_auth, dict) and gateway_auth.get("status") == "gap":
            findings.append(
                Finding(
                    "high",
                    "gateway-auth-coverage-gap",
                    identity,
                    _gap_remediation(row, gateway_auth),
                )
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--assurance", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail while any declared contract or implementation-assurance gap remains",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = args.manifest or root / "config/control-plane-api-surface.yaml"
    assurance_path = args.assurance or root / DEFAULT_ASSURANCE
    manifest = load_yaml(manifest_path)
    assurance = load_assurance(root, assurance_path)
    structural = validate(root, manifest, assurance)
    gaps = coverage_gaps(manifest, assurance)
    findings = structural + (gaps if args.strict and not structural else [])
    payload = {
        "manifest": str(manifest_path.relative_to(root)),
        "assurance": str(assurance_path.relative_to(root)),
        "endpoints": len(manifest.get("endpoints", [])),
        "coverage_gaps": len(gaps),
        "strict": args.strict,
        "status": "PASS" if not findings else "FAIL",
        "findings": [asdict(item) for item in findings],
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "CONTROL_PLANE_API_SURFACE="
            f"{payload['status']} ENDPOINTS={payload['endpoints']} "
            f"COVERAGE_GAPS={payload['coverage_gaps']} STRICT={int(args.strict)}"
        )
        for item in findings:
            print(f"{item.severity.upper()} {item.rule} {item.location}: {item.message}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
