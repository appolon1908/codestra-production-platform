import subprocess
import sys
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.config import settings
from app.entrypoints import (
    event_gateway,
    extension_allocator,
    integration_api,
    notification_worker,
    pjsip_adapter,
    policy_engine,
    scheduler,
    sync_worker,
    telephony_provisioning,
    vicidial_adapter,
    webphone_session_issuer,
)
from app.entrypoints.runtime import worker_app


def route_paths(app):
    return set(app.openapi()["paths"])


def test_api_surfaces_are_narrow_and_cover_existing_routes():
    event_paths = route_paths(event_gateway.app)
    integration_paths = route_paths(integration_api.app)
    assert "/api/v1/events/vicidial" in event_paths
    assert "/api/v2/telephony/canary" in event_paths
    assert "/api/v1/automation/events" in integration_paths
    assert "/api/v1/commands" in integration_paths
    assert "/api/v1/commands/{command_public_id}" in integration_paths
    assert "/api/v1/telephony/commands" in integration_paths
    assert "/api/v1/telephony/commands/{command_public_id}/cancel" in integration_paths
    assert "/api/v1/telephony/operations" in integration_paths
    assert "/api/v1/telephony/operations/{operation_public_id}" in integration_paths
    assert (
        "/api/v1/telephony/operations/{operation_public_id}/transitions"
        in integration_paths
    )
    assert "/api/v1/telephony/results" in integration_paths
    assert "/api/v1/telephony/results/{result_public_id}" in integration_paths
    assert "/api/v1/telephony/reconciliation/runs" in integration_paths
    assert "/api/v1/telephony/reconciliation/runs/{run_public_id}" in integration_paths
    assert "/api/v1/lead-automation/results" in integration_paths
    assert "/api/v1/lead-automation/events/{automation_event_id}" in integration_paths
    assert "/webphone-api/v1/session" in integration_paths
    assert route_paths(policy_engine.app) >= {
        "/api/v1/policy/decisions",
        "/healthz",
        "/readyz",
        "/dependencies",
    }
    assert "/api/v1/events/vicidial" not in route_paths(policy_engine.app)
    assert "/v1/telephony/extensions/reserve" in route_paths(extension_allocator.app)
    assert "/v1/telephony/provisioning" not in route_paths(extension_allocator.app)
    assert "/v1/telephony/provisioning" in route_paths(telephony_provisioning.app)
    assert "/v1/telephony/extensions/reserve" not in route_paths(
        telephony_provisioning.app
    )
    assert "/webphone-api/v1/session" in route_paths(webphone_session_issuer.app)


def test_integration_api_excludes_event_gateway_routes_in_fresh_runtime():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.entrypoints.integration_api import app;"
                "paths=app.openapi()['paths'];"
                "assert not any(p.startswith('/api/v1/events/') for p in paths)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_api_runtime_health_and_correlation(monkeypatch):
    monkeypatch.setattr(settings, "middleware_secret", "unit-test-secret")
    response = TestClient(event_gateway.app).get(
        "/healthz", headers={"X-Correlation-ID": "synthetic-correlation"}
    )
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] != "synthetic-correlation"
    UUID(response.headers["X-Correlation-ID"])
    assert response.headers["Traceparent"].startswith("00-")


def test_disabled_delivery_workers_do_not_claim_or_contact_adapters(monkeypatch):
    monkeypatch.setattr(settings, "odoo_delivery_enabled", False)
    monkeypatch.setattr(settings, "n8n_delivery_enabled", False)
    monkeypatch.setattr(settings, "messaging_enabled", False)
    assert __import__("asyncio").run(sync_worker.cycle()) == {"status": "disabled"}
    assert __import__("asyncio").run(notification_worker.cycle()) == {
        "status": "disabled"
    }


def test_canonical_broad_event_flags_default_closed_and_require_conjunction(
    monkeypatch,
):
    canonical = (
        "send_events",
        "broad_event_delivery_enabled",
        "production_n8n_enabled",
        "n8n_production_workflows_enabled",
    )
    for name in canonical:
        monkeypatch.setattr(settings, name, False)
    assert settings.broad_event_pipeline_enabled is False

    for name in canonical:
        monkeypatch.setattr(settings, name, True)
    assert settings.broad_event_pipeline_enabled is True
    assert settings.enable_external_delivery is False


def test_broad_event_activation_fails_closed_without_exact_bounded_scope(
    monkeypatch,
):
    canonical = (
        "send_events",
        "broad_event_delivery_enabled",
        "production_n8n_enabled",
        "n8n_production_workflows_enabled",
    )
    for name in canonical:
        monkeypatch.setattr(settings, name, True)
    monkeypatch.setattr(settings, "controlled_broad_event_activation", False)
    try:
        settings.validate_safety()
    except ValueError as exc:
        assert "bounded explicit scope" in str(exc)
    else:
        raise AssertionError("unscoped broad-event activation must be rejected")


def test_broad_event_activation_accepts_only_bounded_internal_scope(monkeypatch):
    canonical = (
        "send_events",
        "broad_event_delivery_enabled",
        "production_n8n_enabled",
        "n8n_production_workflows_enabled",
    )
    for name in canonical:
        monkeypatch.setattr(settings, name, True)
    monkeypatch.setattr(settings, "controlled_broad_event_activation", True)
    monkeypatch.setattr(settings, "broad_event_business_unit_allowlist", "BU-400-COD")
    monkeypatch.setattr(settings, "broad_event_campaign_allowlist", "CMP-400-COD")
    monkeypatch.setattr(settings, "broad_event_workflow_allowlist", "existing-id")
    monkeypatch.setattr(settings, "broad_event_type_allowlist", "existing.event")
    monkeypatch.setattr(
        settings, "broad_event_activation_high_water_mark", "2026-07-29T00:00:00Z"
    )
    monkeypatch.setattr(settings, "broad_event_submission_limit", 3)
    monkeypatch.setattr(settings, "enable_external_delivery", False)
    settings.validate_safety()


def test_disabled_scheduler_is_safe(monkeypatch):
    monkeypatch.setattr(settings, "outbox_worker_enabled", False)
    assert __import__("asyncio").run(scheduler.cycle()) == {"status": "disabled"}


def test_telephony_adapters_are_independently_kill_switched(monkeypatch):
    monkeypatch.setattr(settings, "vicidial_provisioning_enabled", False)
    monkeypatch.setattr(settings, "pjsip_provisioning_enabled", False)
    assert __import__("asyncio").run(vicidial_adapter.cycle()) == {
        "result": "kill_switch_closed"
    }
    assert __import__("asyncio").run(pjsip_adapter.cycle()) == {
        "result": "kill_switch_closed"
    }


def test_worker_has_internal_operational_endpoints():
    app = worker_app("test-worker", "test.queue.v1", sync_worker.cycle)
    paths = route_paths(app)
    assert {"/healthz", "/readyz", "/dependencies"} <= paths
    with TestClient(app) as client:
        health = client.get("/healthz")
        readiness = client.get("/readyz")
        assert health.json()["stopping"] is False
        assert readiness.json()["status"] == "ready"
        assert readiness.json()["queue"] == "test.queue.v1"
