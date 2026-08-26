from pathlib import Path

from control_plane_service import server

ROOT = Path(__file__).resolve().parents[1]


def test_release_identity_contains_only_safe_immutable_labels(monkeypatch):
    monkeypatch.setenv("SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("RELEASE_ID", "release-20260823")
    monkeypatch.setenv("IMAGE_DIGEST", "sha256:" + "b" * 64)
    assert server.release_identity() == {
        "service": "codestra-control-plane",
        "source_sha": "a" * 40,
        "release_id": "release-20260823",
        "image_digest": "sha256:" + "b" * 64,
    }


def test_database_snapshot_never_returns_connection_material(monkeypatch):
    monkeypatch.setenv("SYSTEM_DATABASE_NAMES", "control_plane,codestra_odoo")
    monkeypatch.setattr(server.STORE, "list_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(server, "component_status", lambda name: {"status": "unknown"})
    value = server.database_snapshot()
    assert value == {"control_plane": "ready", "codestra_odoo": "unknown"}
    assert "password" not in repr(value).lower()


def test_component_status_fails_closed_when_probe_is_not_configured(monkeypatch):
    monkeypatch.delenv("SYSTEM_ODOO_HEALTH_URL", raising=False)
    assert server.component_status("odoo") == {"status": "unknown", "latency_ms": None}


def test_outbound_safe_mode_requires_every_production_gate(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED", "false")
    monkeypatch.setenv("TELNEXA_MODE", "simulator")
    monkeypatch.setenv("KLYROW_MODE", "test")
    assert server.production_delivery_enabled() is False
    monkeypatch.setenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED", "true")
    monkeypatch.setenv("TELNEXA_MODE", "production")
    monkeypatch.setenv("KLYROW_MODE", "production")
    assert server.production_delivery_enabled() is True


def test_admin_system_routes_are_platform_admin_only():
    source = open(server.__file__, encoding="utf-8").read()
    for path in (
        "/v1/admin/system/health",
        "/v1/admin/system/readiness",
        "/v1/admin/system/databases",
    ):
        assert path in source
    assert 'self.auth_operator({"platform_admin"})' in source


def test_kong_system_route_contract_is_pinned_to_standalone_authority():
    import json

    lock = json.loads((ROOT / "config/kong-source.lock.json").read_text())
    route = next(
        row
        for row in lock["public_routes"]
        if row["route"] == "control-plane-system-admin"
    )
    assert route["methods"] == ["GET"]
    assert route["paths"] == ["/v1/admin/system"]
    assert route["hosts"] == ["api.codestra.co"]
    assert (
        lock["security_contracts"]["system_admin_required_scope"]
        == "platform.admin"
    )
    assert lock["security_contracts"]["authenticated_role_headers"] == [
        "platform_admin",
        "tenant_admin",
    ]


def test_production_compose_configures_private_dependency_probes():
    compose = (ROOT / "deploy/control-plane/compose.yaml").read_text()
    for component in ("KEYCLOAK", "KONG", "MIDDLEWARE", "ODOO", "N8N"):
        assert f"SYSTEM_{component}_HEALTH_URL:" in compose
    assert "codestra-identity_identity_service" in compose
    assert "CONTROL_PLANE_IMAGE_DIGEST" in compose
