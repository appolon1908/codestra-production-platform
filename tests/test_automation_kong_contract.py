from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_automation_routes_require_n8n_oauth_tenant_and_scopes():
    config = yaml.safe_load((ROOT / "deploy/kong/control-plane.yml").read_text())
    service = next(item for item in config["services"] if item["name"] == "codestra-automation-gateway")
    assert {route["name"] for route in service["routes"]} == {
        "automation-policy-check", "automation-result-write",
    }
    oidc = next(plugin for plugin in service["plugins"] if plugin["name"] == "openid-connect")
    assert oidc["config"]["audience"] == ["codestra-middleware"]
    policy = next(plugin for plugin in service["plugins"] if plugin["name"] == "pre-function")["config"]["access"][0]
    for expected in ("codestra-n8n-communications", "communications.message.dispatch",
                     "communications.result.write", "cross_tenant_denied",
                     "KONG_CONTROL_PLANE_GATEWAY_SECRET"):
        assert expected in policy
