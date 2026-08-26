from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.check_control_plane_api_surface import (
    REQUIRED_FIELDS,
    coverage_gaps,
    endpoint_route_predicate_covered,
    implementation_handler_sources,
    load_yaml,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/control-plane-api-surface.yaml"
ASSURANCE_PATH = ROOT / "config/control-plane-api-assurance.yaml"
OPTIONAL_FIELDS = {"remediation", "idempotency_exemption"}


def manifest():
    return load_yaml(MANIFEST_PATH)


def assurance():
    return load_yaml(ASSURANCE_PATH)


def test_control_plane_api_inventory_matches_current_sources() -> None:
    assert validate(ROOT, manifest(), assurance()) == []


def test_endpoint_rows_contain_only_governed_fields() -> None:
    unexpected = {
        row["endpoint_id"]: sorted(set(row) - REQUIRED_FIELDS - OPTIONAL_FIELDS)
        for row in manifest()["endpoints"]
        if set(row) - REQUIRED_FIELDS - OPTIONAL_FIELDS
    }
    assert unexpected == {}


def test_missing_contract_and_implementation_layers_are_explicit_and_owned() -> None:
    gaps = coverage_gaps(manifest(), assurance())
    assert gaps
    identities = {finding.location for finding in gaps}
    assert "postal-inbound" in identities
    assert "crm-account" in identities
    assert "mapping-job-read" in identities
    assert "crawler-retry" in identities
    assert "source-event-ingest" in identities
    assert all(finding.message for finding in gaps)


def test_strict_predeployment_api_coverage_gate_fails_closed() -> None:
    result = subprocess.run(
        [sys.executable, "tools/check_control_plane_api_surface.py", "--strict"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "CONTROL_PLANE_API_SURFACE=FAIL" in result.stdout
    assert "COVERAGE_GAPS=" in result.stdout


def test_public_business_apis_are_never_marked_kong_not_required() -> None:
    unsafe = [
        row["endpoint_id"]
        for row in manifest()["endpoints"]
        if row["exposure"] == "public_api" and row["kong"] == "not_required"
    ]
    assert unsafe == []


def test_mutating_apis_declare_idempotency() -> None:
    mutating = {"POST", "PUT", "PATCH", "DELETE"}
    missing = [
        row["endpoint_id"]
        for row in manifest()["endpoints"]
        if mutating.intersection(row["methods"])
        and row["idempotency"] not in {"required", "exempt"}
    ]
    assert missing == []


def test_idempotency_is_proven_or_reported_as_an_implementation_gap() -> None:
    gaps = {
        finding.location
        for finding in coverage_gaps(manifest(), assurance())
        if finding.rule == "idempotency-implementation-gap"
    }
    assert "crawler-retry" in gaps
    assert "crawler-cancel" in gaps
    assert "crawler-create" not in gaps
    assert "message-create-sms" not in gaps


def test_event_ingest_gateway_auth_mismatch_is_fail_closed() -> None:
    gateway_gaps = {
        finding.location
        for finding in coverage_gaps(manifest(), assurance())
        if finding.rule == "gateway-auth-coverage-gap"
    }
    assert gateway_gaps == {
        "api-health",
        "messages-api-list",
        "source-event-ingest",
    }


def test_route_fragments_must_share_one_branch_predicate() -> None:
    source = (ROOT / "control_plane_service/server.py").read_text(encoding="utf-8")
    handler = implementation_handler_sources(source)["do_POST"]
    tokens = ['"/v1/messages/"', '"/retry"']
    assert endpoint_route_predicate_covered(handler, tokens)

    message_retry_removed = handler.replace(
        'parsed.path.startswith("/v1/messages/") and '
        'parsed.path.endswith(("/cancel","/retry"))',
        'parsed.path.startswith("/v1/messages/") and '
        'parsed.path.endswith(("/cancel",))',
    )
    assert '"/retry"' in message_retry_removed  # crawler retry remains elsewhere
    assert not endpoint_route_predicate_covered(message_retry_removed, tokens)


def test_implementation_tokens_are_bound_to_the_declared_http_method(tmp_path) -> None:
    (tmp_path / "implementation.py").write_text(
        "class Handler:\n"
        "    def do_GET(self):\n"
        "        return None\n"
        "    def do_POST(self):\n"
        "        value = \"/method-bound\"\n",
        encoding="utf-8",
    )
    (tmp_path / "openapi.yaml").write_text("paths: {}\n", encoding="utf-8")
    (tmp_path / "kong.yaml").write_text("services: []\n", encoding="utf-8")
    (tmp_path / "registry.yaml").write_text("endpoints: []\n", encoding="utf-8")
    value = {
        "version": 1,
        "implementation": "implementation.py",
        "openapi": "openapi.yaml",
        "kong": "kong.yaml",
        "registry": "registry.yaml",
        "endpoints": [
            {
                "endpoint_id": "method-bound",
                "methods": ["GET"],
                "path": "/method-bound",
                "implementation_tokens": ['"/method-bound"'],
                "exposure": "private_api",
                "auth": "private_network",
                "scope": "none",
                "tenant_required": False,
                "idempotency": "not_required",
                "openapi": "not_required",
                "kong": "not_required",
                "registry": "not_required",
                "lifecycle": "source_ready",
                "owner": "middleware-platform",
            }
        ],
    }
    findings = validate(
        tmp_path,
        value,
        {"version": 1, "handlers": {}, "endpoints": {}},
    )
    assert any(
        finding.rule == "implementation-token" and finding.location == "method-bound"
        for finding in findings
    )


def test_message_event_branch_has_exact_method_bound_evidence() -> None:
    source = (ROOT / "control_plane_service/server.py").read_text(encoding="utf-8")
    handler = implementation_handler_sources(source)["do_GET"]
    token = assurance()["endpoints"]["messages-events"]["tokens"][0]
    assert token in handler
    assert token not in handler.replace(token, "event_request=False")
