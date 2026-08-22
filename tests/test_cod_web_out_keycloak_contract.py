import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cod_web_out_machine_client_is_least_privilege_and_secret_free():
    path = ROOT / "deploy/keycloak/cod-web-out-email-production.json"
    raw = path.read_text(encoding="utf-8")
    contract = json.loads(raw)

    assert contract["issuer"] == "https://auth.codestra.co/realms/codestra"
    assert contract["clientId"] == "cod-web-out-email-production"
    assert contract["serviceAccountsEnabled"] is True
    assert contract["publicClient"] is False
    assert contract["standardFlowEnabled"] is False
    assert contract["directAccessGrantsEnabled"] is False
    assert contract["fullScopeAllowed"] is False
    assert contract["accessTokenLifespanSeconds"] == 300
    assert contract["tenantClaim"] == {
        "name": "tenant_id", "value": "COD", "source": "server",
    }
    assert set(contract["defaultClientScopes"]) == {
        "campaign.cod-web-out", "email.send", "email.status", "klyrow.read", "klyrow.send",
    }
    assert "communications.admin" in contract["deniedScopes"]
    assert contract["secretFile"].startswith("/etc/codestra/secrets/")
    assert "clientSecret" not in contract
    assert "secretValue" not in contract
    assert "Bearer " not in raw
