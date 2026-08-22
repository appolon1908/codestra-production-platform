import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_communications_oauth_contract_is_least_privilege():
    contract = json.loads((ROOT / "deploy/keycloak/communications-oauth.json").read_text())
    assert contract["issuer"] == "https://auth.codestra.co/realms/codestra"
    assert contract["audience"] == "codestra-middleware"
    assert contract["access_token_lifespan_seconds"] == 300
    assert len(contract["scopes"]) == 14
    assert len(set(contract["scopes"])) == 14
    assert contract["tenant_claim"] == {"name": "tenant_id", "source": "server", "value": "COD"}
    for scopes in contract["clients"].values():
        assert "communications.admin" not in scopes
    assert "communications.result.write" not in contract["clients"]["codestra-odoo-communications"]
    assert "communications.reconciliation.execute" not in contract["clients"]["codestra-odoo-communications"]
