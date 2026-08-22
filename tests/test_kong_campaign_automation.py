import json
from pathlib import Path

from scripts.reconcile_kong_campaign_automation import claim_guard, rsa_public_key_pem


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
