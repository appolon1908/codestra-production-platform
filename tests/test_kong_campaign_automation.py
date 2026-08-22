import json
from pathlib import Path

import pytest

from scripts.reconcile_kong_campaign_automation import (
    active_rsa_key,
    claim_guard,
    plugin_form,
    require_exact_fields,
    rsa_public_key_pem,
    select_managed_route,
    ensure_plugin,
)


ROOT = Path(__file__).parents[1]


def test_manifest_is_exact_and_scope_separated():
    manifest = json.loads((ROOT / "config/kong-campaign-automation-routes.json").read_text())
    assert manifest["consumer"]["custom_id"] == "codestra-n8n-campaign-crm-production"
    assert manifest["audience"] == "codestra-middleware"
    assert manifest["environment"] == "production"
    assert {(row["path"], row["scope"]) for row in manifest["routes"]} == {
        ("/api/v1/automation/policy-check", "n8n.policy.check"),
        ("/api/v1/integrations/n8n/results", "n8n.results.submit"),
    }
    for route in manifest["routes"]:
        guard = claim_guard(manifest, route["scope"])
        assert route["scope"] in guard
        assert "invalid_issuer" in guard
        assert "invalid_audience" in guard
        assert "service_identity_denied" in guard


def test_rsa_jwk_conversion_is_public_key_pem():
    pem = rsa_public_key_pem({"n": "sXch", "e": "AQAB"})
    assert pem.startswith("-----BEGIN PUBLIC KEY-----\n")
    assert pem.endswith("-----END PUBLIC KEY-----\n")


def test_exact_verification_rejects_live_drift():
    with pytest.raises(RuntimeError, match="configuration drift"):
        require_exact_fields({"methods": ["GET"]}, {"methods": ["POST"]}, "route")


def test_plugin_config_is_form_encoded_for_kong_admin_api():
    assert plugin_form({"claims_to_verify": ["exp"], "run_on_preflight": True}) == {
        "config.claims_to_verify[]": ["exp"],
        "config.run_on_preflight": True,
    }


def test_existing_plugin_patch_includes_immutable_plugin_name(monkeypatch):
    calls = []

    def fake_request(_admin, method, path, payload=None):
        calls.append((method, path, payload))
        if method == "GET" and path == "/routes/route-1/plugins":
            return {"data": [{"id": "plugin-1", "name": "jwt", "enabled": True}]}
        if method == "GET" and path == "/plugins/plugin-1":
            return {"name": "jwt", "config": {"key_claim_name": "azp"}}
        return {}

    monkeypatch.setattr(
        "scripts.reconcile_kong_campaign_automation.request", fake_request
    )
    ensure_plugin("http://kong", "route-1", "jwt", {"key_claim_name": "azp"}, True)
    assert ("PATCH", "/plugins/plugin-1", {
        "name": "jwt", "config.key_claim_name": "azp"
    }) in calls


def test_legacy_same_path_route_is_adopted_only_during_apply():
    legacy = {
        "id": "legacy", "name": "automation-policy-check",
        "hosts": ["api.codestra.co"], "paths": ["/policy"], "methods": ["POST"],
    }
    with pytest.raises(RuntimeError, match="requires managed adoption"):
        select_managed_route([legacy], "managed-policy", "api.codestra.co", "/policy", False)
    assert select_managed_route(
        [legacy], "managed-policy", "api.codestra.co", "/policy", True
    ) == legacy


def test_duplicate_same_path_route_is_rejected():
    managed = {
        "id": "managed", "name": "managed-policy",
        "hosts": ["api.codestra.co"], "paths": ["/policy"], "methods": ["POST"],
    }
    legacy = {**managed, "id": "legacy", "name": "legacy-policy"}
    with pytest.raises(RuntimeError, match="conflicting live route"):
        select_managed_route(
            [managed, legacy], "managed-policy", "api.codestra.co", "/policy", True
        )


def test_overlapping_jwks_selects_fresh_token_kid(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    response = Response()
    monkeypatch.setattr(
        "scripts.reconcile_kong_campaign_automation.urlopen", lambda *_args, **_kwargs: response
    )
    monkeypatch.setattr(
        "scripts.reconcile_kong_campaign_automation.json.load",
        lambda _response: {"keys": [
            {"kid": "old", "kty": "RSA", "alg": "RS256", "use": "sig"},
            {"kid": "new", "kty": "RSA", "alg": "RS256", "use": "sig"},
        ]},
    )
    assert active_rsa_key("https://issuer/certs", "new")["kid"] == "new"
    with pytest.raises(RuntimeError, match="--active-kid"):
        active_rsa_key("https://issuer/certs")
