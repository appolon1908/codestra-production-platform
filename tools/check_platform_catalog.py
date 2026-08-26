#!/usr/bin/env python3
"""Validate the Codestra service, feature, API, and deployment-gap catalog."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


SYSTEM_FIELDS = {"system_id", "owner", "class", "source_roots", "runtime_boundary"}
FEATURE_FIELDS = {
    "feature_id",
    "owner",
    "system_id",
    "lifecycle",
    "runtime_default",
    "side_effects",
    "deployment_candidate",
    "dependencies",
    "contracts",
}
API_FIELDS = {
    "api_id",
    "feature_id",
    "method",
    "host",
    "path",
    "exposure",
    "ingress",
    "auth",
    "scope",
    "idempotency",
    "owner",
    "lifecycle",
    "contract",
}
GAP_FIELDS = {
    "gap_id",
    "severity",
    "status",
    "owner",
    "required_before_server_push",
    "affected_features",
    "remediation",
}

LIFECYCLES = {"active", "source_ready", "staging", "planned", "deprecated"}
RUNTIME_DEFAULTS = {"enabled", "disabled"}
SIDE_EFFECTS = {"none", "read_only", "internal_writes", "external_writes", "telephony"}
EXPOSURES = {"public_api", "public_health", "browser_application", "private_mtls", "private_api"}
INGRESSES = {"kong", "caddy_health", "caddy_browser", "caddy_private_mtls", "internal_service"}
IDEMPOTENCY = {"required", "not_required", "exempt"}
GAP_STATUSES = {"open", "in_progress", "resolved", "accepted_risk"}
SEVERITIES = {"critical", "high", "medium", "low"}
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXTERNAL_PREFIXES = ("external:", "pr:", "repo:")


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    location: str
    message: str


def load_catalog(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return value


def _missing(value: dict[str, Any], fields: set[str]) -> list[str]:
    return sorted(fields - set(value))


def _unique(values: Iterable[dict[str, Any]], key: str, kind: str) -> list[Finding]:
    seen: set[str] = set()
    findings: list[Finding] = []
    for row in values:
        identity = str(row.get(key, "<missing>"))
        if identity in seen:
            findings.append(Finding("critical", f"duplicate-{kind}", identity, "identifier is not unique"))
        seen.add(identity)
    return findings


def _local_reference(reference: str) -> bool:
    return not reference.startswith(EXTERNAL_PREFIXES)


def validate_catalog(root: Path, catalog: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if catalog.get("version") != 1:
        findings.append(Finding("critical", "catalog-version", "config/platform-catalog.yaml", "version must be 1"))

    systems = catalog.get("systems", [])
    features = catalog.get("features", [])
    apis = catalog.get("apis", [])
    gaps = catalog.get("known_gaps", [])
    for name, value in (("systems", systems), ("features", features), ("apis", apis), ("known_gaps", gaps)):
        if not isinstance(value, list):
            findings.append(Finding("critical", "catalog-schema", name, "must be a list"))

    if findings:
        return findings

    findings += _unique(systems, "system_id", "system")
    findings += _unique(features, "feature_id", "feature")
    findings += _unique(apis, "api_id", "api")
    findings += _unique(gaps, "gap_id", "gap")

    system_ids = {str(row.get("system_id")) for row in systems}
    feature_ids = {str(row.get("feature_id")) for row in features}

    for row in systems:
        identity = str(row.get("system_id", "<missing>"))
        if missing := _missing(row, SYSTEM_FIELDS):
            findings.append(Finding("critical", "system-schema", identity, f"missing fields: {', '.join(missing)}"))
            continue
        for reference in row["source_roots"]:
            reference = str(reference)
            if _local_reference(reference) and not (root / reference).exists():
                findings.append(Finding("critical", "missing-source-root", identity, reference))

    for row in features:
        identity = str(row.get("feature_id", "<missing>"))
        if missing := _missing(row, FEATURE_FIELDS):
            findings.append(Finding("critical", "feature-schema", identity, f"missing fields: {', '.join(missing)}"))
            continue
        if row["system_id"] not in system_ids:
            findings.append(Finding("critical", "feature-system", identity, f"unknown system: {row['system_id']}"))
        if row["lifecycle"] not in LIFECYCLES:
            findings.append(Finding("critical", "feature-lifecycle", identity, str(row["lifecycle"])))
        if row["runtime_default"] not in RUNTIME_DEFAULTS:
            findings.append(Finding("critical", "feature-runtime-default", identity, str(row["runtime_default"])))
        if row["side_effects"] not in SIDE_EFFECTS:
            findings.append(Finding("critical", "feature-side-effects", identity, str(row["side_effects"])))
        if row["runtime_default"] == "enabled" and row["lifecycle"] != "active":
            findings.append(Finding("critical", "unsafe-feature-default", identity, "only active features may default enabled"))
        if row["runtime_default"] == "enabled" and row["side_effects"] in {"external_writes", "telephony"}:
            findings.append(Finding("critical", "unsafe-side-effect-default", identity, "external delivery and telephony must default disabled"))
        for dependency in row["dependencies"]:
            if dependency not in system_ids:
                findings.append(Finding("critical", "feature-dependency", identity, f"unknown system: {dependency}"))
        for reference in row["contracts"]:
            reference = str(reference)
            if _local_reference(reference) and not (root / reference).exists():
                findings.append(Finding("critical", "missing-feature-contract", identity, reference))

    route_keys: set[tuple[str, str, str]] = set()
    for row in apis:
        identity = str(row.get("api_id", "<missing>"))
        if missing := _missing(row, API_FIELDS):
            findings.append(Finding("critical", "api-schema", identity, f"missing fields: {', '.join(missing)}"))
            continue
        method = str(row["method"]).upper()
        path = str(row["path"])
        host = str(row["host"])
        route_key = (host, method, path)
        if route_key in route_keys:
            findings.append(Finding("critical", "duplicate-api-route", identity, f"{host} {method} {path}"))
        route_keys.add(route_key)
        if row["feature_id"] not in feature_ids:
            findings.append(Finding("critical", "api-feature", identity, f"unknown feature: {row['feature_id']}"))
        if row["exposure"] not in EXPOSURES:
            findings.append(Finding("critical", "api-exposure", identity, str(row["exposure"])))
        if row["ingress"] not in INGRESSES:
            findings.append(Finding("critical", "api-ingress", identity, str(row["ingress"])))
        if row["lifecycle"] not in LIFECYCLES:
            findings.append(Finding("critical", "api-lifecycle", identity, str(row["lifecycle"])))
        if row["idempotency"] not in IDEMPOTENCY:
            findings.append(Finding("critical", "api-idempotency", identity, str(row["idempotency"])))
        if not path.startswith("/"):
            findings.append(Finding("critical", "api-path", identity, "path must start with /"))
        if row["exposure"] == "public_api" and row["ingress"] != "kong":
            findings.append(Finding("critical", "public-api-bypass", identity, "public business APIs must enter through Kong"))
        if row["exposure"] == "browser_application" and row["ingress"] != "caddy_browser":
            findings.append(Finding("critical", "browser-ingress", identity, "browser applications require the reviewed Caddy boundary"))
        if row["exposure"] == "private_mtls" and row["ingress"] != "caddy_private_mtls":
            findings.append(Finding("critical", "private-mtls-ingress", identity, "private mTLS APIs require the private Caddy boundary"))
        if row["exposure"] == "public_health" and row["ingress"] not in {"caddy_health", "kong"}:
            findings.append(Finding("critical", "health-ingress", identity, "public health must use a health-only Caddy or Kong route"))
        if row["exposure"] == "public_api" and str(row["auth"]).lower() == "none":
            findings.append(Finding("critical", "public-api-auth", identity, "public business APIs must authenticate"))
        if method in MUTATING_METHODS and row["idempotency"] == "not_required":
            findings.append(Finding("critical", "mutation-idempotency", identity, "mutation requires idempotency or a documented exemption"))
        if row["idempotency"] == "exempt" and not row.get("idempotency_exemption"):
            findings.append(Finding("critical", "idempotency-exemption", identity, "exemption reason is required"))
        reference = str(row["contract"])
        if _local_reference(reference) and not (root / reference).exists():
            findings.append(Finding("critical", "missing-api-contract", identity, reference))

    for row in gaps:
        identity = str(row.get("gap_id", "<missing>"))
        if missing := _missing(row, GAP_FIELDS):
            findings.append(Finding("critical", "gap-schema", identity, f"missing fields: {', '.join(missing)}"))
            continue
        if row["severity"] not in SEVERITIES:
            findings.append(Finding("critical", "gap-severity", identity, str(row["severity"])))
        if row["status"] not in GAP_STATUSES:
            findings.append(Finding("critical", "gap-status", identity, str(row["status"])))
        unknown = sorted(set(row["affected_features"]) - feature_ids)
        if unknown:
            findings.append(Finding("critical", "gap-feature", identity, f"unknown features: {', '.join(unknown)}"))
        if row["status"] == "resolved" and not row.get("resolution"):
            findings.append(Finding("critical", "gap-resolution", identity, "resolved gaps require resolution evidence"))

    for name, reference in catalog.get("canonical_sources", {}).items():
        if _local_reference(str(reference)) and not (root / str(reference)).exists():
            findings.append(Finding("critical", "missing-canonical-source", name, str(reference)))

    return findings


def deployment_blockers(catalog: dict[str, Any], requested_features: set[str]) -> list[Finding]:
    features = {row["feature_id"]: row for row in catalog.get("features", [])}
    if not requested_features:
        requested_features = {
            feature_id
            for feature_id, row in features.items()
            if row.get("deployment_candidate") is True
        }
    blockers: list[Finding] = []
    unknown = sorted(requested_features - set(features))
    for feature_id in unknown:
        blockers.append(Finding("critical", "unknown-deployment-feature", feature_id, "feature is absent from catalog"))
    for gap in catalog.get("known_gaps", []):
        if not gap.get("required_before_server_push"):
            continue
        if gap.get("status") in {"resolved", "accepted_risk"}:
            continue
        affected = set(gap.get("affected_features", []))
        if requested_features.intersection(affected):
            blockers.append(Finding(str(gap["severity"]), "deployment-gap", str(gap["gap_id"]), str(gap["remediation"])))
    for feature_id in requested_features.intersection(features):
        row = features[feature_id]
        if row["lifecycle"] not in {"active", "source_ready"}:
            blockers.append(Finding("critical", "feature-not-deployable", feature_id, f"lifecycle is {row['lifecycle']}"))
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--deployment-check", action="store_true")
    parser.add_argument("--feature", action="append", default=[])
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    root = args.root.resolve()
    catalog_path = args.catalog or root / "config/platform-catalog.yaml"
    catalog = load_catalog(catalog_path)
    findings = validate_catalog(root, catalog)
    if args.deployment_check and not findings:
        findings.extend(deployment_blockers(catalog, set(args.feature)))

    payload = {
        "catalog": str(catalog_path.relative_to(root)),
        "systems": len(catalog.get("systems", [])),
        "features": len(catalog.get("features", [])),
        "apis": len(catalog.get("apis", [])),
        "gaps": len(catalog.get("known_gaps", [])),
        "deployment_check": args.deployment_check,
        "findings": [asdict(item) for item in findings],
        "status": "PASS" if not findings else "FAIL",
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "PLATFORM_CATALOG=" + payload["status"]
            + f" SYSTEMS={payload['systems']} FEATURES={payload['features']}"
            + f" APIS={payload['apis']} GAPS={payload['gaps']}"
        )
        for item in findings:
            print(f"{item.severity.upper()} {item.rule} {item.location}: {item.message}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
