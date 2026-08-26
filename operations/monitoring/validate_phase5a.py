#!/usr/bin/env python3
"""Static, fail-closed Phase 5A monitoring validation."""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MON = ROOT / "operations/monitoring"
REQUIRED_LABELS = {"severity", "service", "environment", "owner_ref"}
REQUIRED_ANNOTATIONS = {
    "summary", "description", "current_value", "threshold", "threshold_status",
    "runbook", "runbook_url", "dashboard",
}
RUNBOOK_HEADINGS = {f"## {n}." for n in range(1, 14)}
SECRET_PATTERNS = (
    re.compile(r"(?i)(password|token|secret|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@"),
)


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    rules_doc = yaml.safe_load((MON / "rules/platform.rules.yml").read_text())
    rules = [rule for group in rules_doc["groups"] for rule in group["rules"]]
    critical = [rule for rule in rules if rule["labels"]["severity"] == "critical"]
    names = [rule["alert"] for rule in rules]
    if len(names) != len(set(names)):
        fail("duplicate alert names")

    matrix = list(csv.DictReader((MON / "RULE-COVERAGE-MATRIX.tsv").open(), delimiter="\t"))
    if not matrix or len(matrix) != len(critical):
        fail(f"coverage mismatch matrix={len(matrix)} critical={len(critical)}")
    critical_names = {rule["alert"] for rule in critical}
    if {row["alertname"] for row in matrix} != critical_names:
        fail("coverage matrix and critical rules differ")

    for rule in critical:
        missing_labels = REQUIRED_LABELS - rule.get("labels", {}).keys()
        missing_annotations = REQUIRED_ANNOTATIONS - rule.get("annotations", {}).keys()
        if missing_labels or missing_annotations or not rule.get("for"):
            fail(f"{rule['alert']}: labels={missing_labels} annotations={missing_annotations}")
        if rule["labels"]["owner_ref"] != "monitoring-owner-registry":
            fail(f"{rule['alert']}: invalid owner reference")
        if rule["annotations"]["threshold_status"] != "candidate_requires_post_deployment_tuning":
            fail(f"{rule['alert']}: threshold status")
        runbook = ROOT / rule["annotations"]["runbook"]
        if not runbook.is_file():
            fail(f"{rule['alert']}: missing runbook")
        text = runbook.read_text()
        for heading in RUNBOOK_HEADINGS:
            if heading not in text:
                fail(f"{rule['alert']}: missing {heading}")

    alertmanager = yaml.safe_load((MON / "alertmanager.example.yml").read_text())
    routes = alertmanager["route"]["routes"]
    protected = {"approved-primary-receiver", "approved-secondary-receiver", "approved-recovery-receiver"}
    for route in routes:
        if route["receiver"] in protected and 'environment="production"' not in route["matchers"]:
            fail(f"unscoped production route: {route['receiver']}")
        if "test" in route["receiver"]:
            fail("test receiver in production template")
    if alertmanager["route"]["receiver"] != "fail-closed-unrouted":
        fail("default route is not fail closed")
    for receiver in alertmanager["receivers"]:
        for webhook in receiver.get("webhook_configs", []):
            if "url" in webhook:
                fail(f"inline URL in production template: {receiver['name']}")
        if receiver["name"] in protected:
            for webhook in receiver["webhook_configs"]:
                if "url" in webhook or not webhook.get("url_file", "").startswith("/run/secrets/"):
                    fail(f"unsafe receiver {receiver['name']}")

    scan_paths = [
        MON / "rules/platform.rules.yml",
        MON / "alertmanager.example.yml",
        MON / "compose.monitoring.yaml",
        *sorted((ROOT / "operations/runbooks/alerts").glob("*.md")),
    ]
    for path in scan_paths:
        text = path.read_text()
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                fail(f"possible secret in {path}")

    print(
        f"phase5a_static_validation=PASS rules={len(rules)} critical={len(critical)} "
        f"runbooks={len(critical)} duplicates=0 routing=PASS secrets=PASS"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"phase5a_static_validation=FAIL reason={exc}", file=sys.stderr)
        raise SystemExit(1)
