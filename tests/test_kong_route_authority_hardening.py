import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/kong-canonical-middleware-routes.json"
RECONCILER_PATH = ROOT / "scripts/reconcile_kong_canonical_routes.py"
EXPORTER_PATH = ROOT / "scripts/export_kong_public_route_contracts.py"
CONTROL_PLANE_PATH = ROOT / "deploy/kong/control-plane.yml"
SCOPE_POLICY_PATH = ROOT / "deploy/kong/scope-policy.lua"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module():
    return _load(RECONCILER_PATH, "reconcile_kong_canonical_routes")


def _exporter():
    return _load(EXPORTER_PATH, "export_kong_public_route_contracts")


def _inline_scope_policy() -> str:
    document = yaml.safe_load(CONTROL_PLANE_PATH.read_text())
    plugins = document["services"][0]["plugins"]
    pre_function = next(plugin for plugin in plugins if plugin["name"] == "pre-function")
    return pre_function["config"]["access"][0].strip()


def test_public_route_manifest_disables_legacy_and_name_only_trust():
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest["schema"] == "codestra.kong.canonical-routes.v2"
    assert manifest["legacyHost"] == "api.codestra.agency"
    assert manifest["legacyHostEnabled"] is False
    assert "allowedExistingRouteNames" not in manifest
    assert manifest["unverifiedExistingRouteNames"]
    approved = {
        item["name"] for item in manifest["routes"] + manifest["contractRoutes"]
    }
    assert approved.isdisjoint(manifest["unverifiedExistingRouteNames"])


def test_contract_routes_bind_exact_dedicated_security_authority():
    manifest = json.loads(MANIFEST_PATH.read_text())
    for route in manifest["contractRoutes"]:
        authority = ROOT / route["securityAuthority"]
        assert authority.is_file()
        assert route["hosts"] == ["api.codestra.co"]
        assert route["serviceHost"] == "codestra-middleware-integration-api-1"
        assert route["servicePort"] == 8095
        assert {"jwt", "correlation-id", "rate-limiting", "request-size-limiting"} <= set(
            route["requiredPlugins"]
        )
        assert {"pre-function", "post-function"} & set(route["requiredPlugins"])


def test_reconciler_pagination_cannot_leave_the_selected_admin_origin():
    module = _module()
    assert module.safe_next("http://127.0.0.1:8001", "/routes?offset=next") == (
        "http://127.0.0.1:8001/routes?offset=next"
    )
    assert module.safe_next(
        "http://127.0.0.1:8001", "http://127.0.0.1:8001/routes?offset=next"
    ) == "http://127.0.0.1:8001/routes?offset=next"
    with pytest.raises(RuntimeError, match="unsafe Kong pagination URL"):
        module.safe_next(
            "http://127.0.0.1:8001", "https://attacker.invalid/routes?offset=next"
        )


def test_reconciler_is_exact_and_never_unions_legacy_hosts():
    source = RECONCILER_PATH.read_text()
    assert "name-only public route allowlists are forbidden" in source
    assert "name-only public routes require exact source contracts" in source
    assert "unsafe Kong pagination URL" in source
    assert 'desired_hosts = [manifest["canonicalHost"]]' in source
    assert "original_hosts +" not in source
    assert "LEGACY_PUBLIC_ROUTE_NAMES" in source
    assert "duplicate enabled route plugins" in source
    assert "securityAuthority" in source
    assert "correlation-id" in source
    assert 'return "true" if value else "false"' in source


def test_read_only_route_exporter_redacts_secret_values_without_exporting_credentials():
    module = _exporter()
    source = EXPORTER_PATH.read_text()
    value = {
        "client_secret": "do-not-export",
        "nested": {"password": "do-not-export", "secret_is_base64": True},
        "key_claim_name": "azp",
        "allowed_payload_size": 2,
    }
    sanitized = module.sanitize(value)
    assert sanitized["client_secret"] == "REDACTED"
    assert sanitized["nested"]["password"] == "REDACTED"
    assert sanitized["nested"]["secret_is_base64"] is True
    assert sanitized["key_claim_name"] == "azp"
    assert "method=\"GET\"" in source
    assert "credentials_exported" in source
    assert "consumers" not in source.lower()
    assert "unsafe Kong pagination URL" in source


def test_exporter_pagination_cannot_leave_the_selected_admin_origin():
    module = _exporter()
    with pytest.raises(RuntimeError, match="unsafe Kong pagination URL"):
        module.safe_next(
            "http://127.0.0.1:8001", "http://attacker.invalid/routes?offset=next"
        )


def test_inline_and_standalone_control_plane_scope_policies_are_identical():
    assert _inline_scope_policy() == SCOPE_POLICY_PATH.read_text().strip()


def test_control_plane_scope_policy_covers_exact_admin_and_message_roots():
    policy = SCOPE_POLICY_PATH.read_text()
    assert 'path == "/v1/admin/system" or path:find("^/v1/admin/system/")' in policy
    assert 'required = "platform.admin"' in policy
    assert 'path == "/api/v1/messages" or path:find("^/api/v1/messages/")' in policy
    assert 'required = "communications.message.read"' in policy
    assert 'error="route_scope_undefined"' in policy
    assert 'path == "/api/v1/health"' in policy
    assert 'path:find("^/api/v1/events/")' in policy
    assert 'X-Authenticated-Role", "platform_admin"' in policy


def test_undefined_control_plane_paths_are_denied_before_proxy_identity_headers():
    policy = SCOPE_POLICY_PATH.read_text()
    deny = policy.index('return kong.response.exit(403,{error="route_scope_undefined"})')
    identity = policy.index('kong.service.request.set_header("X-Authenticated-Client"')
    assert deny < identity
