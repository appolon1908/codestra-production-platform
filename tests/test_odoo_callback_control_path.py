import json
from pathlib import Path


IDENTITY = json.loads(Path("config/keycloak-odoo-callback-client.json").read_text())
KONG_LOCK = json.loads(Path("config/kong-source.lock.json").read_text())
CALLBACK_CONTRACT = KONG_LOCK["external_route_contracts"]["callback"]["document"]
DEPLOYMENT = Path("deploy/odoo-callback/compose.synthetic-only.yaml").read_text()


def test_odoo_callback_identity_is_bounded_and_has_no_secret():
    client = IDENTITY["client"]
    assert client["clientId"] == "codestra-odoo-callback-service"
    assert client["serviceAccountsEnabled"] is True
    assert client["standardFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert client["implicitFlowEnabled"] is False
    assert client["fullScopeAllowed"] is False
    assert client["defaultClientScopes"] == ["roles"]
    assert set(client["optionalClientScopes"]) == {
        "callbacks.read",
        "callbacks.write",
    }
    assert IDENTITY["serviceAccountRealmRoles"] == ["service"]
    assert IDENTITY["clientRealmRoleScopeMappings"] == ["service"]
    assert IDENTITY["delivery"]["syntheticOnly"] is True
    serialized = json.dumps(IDENTITY)
    assert '"clientSecret"' not in serialized
    assert '"secretValue"' not in serialized
    assert IDENTITY["delivery"]["secretInSource"] is False


def test_identity_claims_are_exactly_cod_test_syn_and_callback_audience():
    mappers = {
        item["name"]: item
        for item in IDENTITY["client"]["protocolMappers"]
    }
    assert (
        mappers["callback-api-audience"]["config"][
            "included.client.audience"
        ]
        == CALLBACK_CONTRACT["audience"]
    )
    assert (
        mappers["callback-tenant"]["config"]["claim.value"]
        == CALLBACK_CONTRACT["tenant"]
    )
    assert json.loads(
        mappers["callback-campaigns"]["config"]["claim.value"]
    ) == [CALLBACK_CONTRACT["campaign"]]
    roles = mappers["callback-service-realm-roles"]
    assert roles["protocolMapper"] == "oidc-usermodel-realm-role-mapper"
    assert roles["config"]["claim.name"] == "realm_access.roles"
    assert roles["config"]["access.token.claim"] == "true"


def test_kong_callback_contract_is_pinned_to_standalone_authority():
    assert KONG_LOCK["repository"] == "appolon1908-hue/Kong"
    assert (
        KONG_LOCK["commit"]
        == "007055bbd05b9cd1c7cc33d3810ec17a3ec9fbba"
    )
    assert KONG_LOCK["production_state_changed"] is False
    assert CALLBACK_CONTRACT["consumer"] == {
        "username": "codestra-odoo-callback-service",
        "custom_id": "codestra-odoo-callback-service",
    }
    assert CALLBACK_CONTRACT["requiredRole"] == "service"
    assert CALLBACK_CONTRACT["service"] == {
        "name": "codestra-callback-api",
        "protocol": "http",
        "host": "codestra-middleware-integration-api-1",
        "port": 8095,
        "retries": 1,
        "connect_timeout": 3000,
        "read_timeout": 10000,
        "write_timeout": 10000,
    }
    assert {
        (tuple(route["methods"]), tuple(route["paths"]), route["requiredScope"])
        for route in CALLBACK_CONTRACT["routes"]
    } == {
        (("POST",), ("/api/v1/control/callbacks",), "callbacks.write"),
        (("GET",), ("/api/v1/callbacks",), "callbacks.read"),
    }


def test_deployment_keeps_every_broad_delivery_path_disabled():
    assert 'CODESTRA_CALLBACK_SYNC_ENABLED: "true"' in DEPLOYMENT
    assert (
        'CODESTRA_CALLBACK_TOKEN_URL: '
        '"http://keycloak:8080/realms/codestra/protocol/openid-connect/token"'
        in DEPLOYMENT
    )
    assert (
        'CALLBACK_JWT_ISSUER: "https://auth.codestra.co/realms/codestra"'
        in DEPLOYMENT
    )
    assert 'CALLBACK_JWT_AUDIENCE: "codestra-callback-api"' in DEPLOYMENT
    assert (
        'CALLBACK_JWT_JWKS_URL: '
        '"http://keycloak:8080/realms/codestra/protocol/openid-connect/certs"'
        in DEPLOYMENT
    )
    assert "codestra-odoo-callback-service" in DEPLOYMENT
    assert "exact reviewed addon release required" in DEPLOYMENT
    assert "exact reviewed campaign dependency release required" in DEPLOYMENT
    assert "/mnt/extra-addons/call_center_campaign:ro" in DEPLOYMENT
    for setting in (
        "CALLBACK_EMAIL_COMMAND_ENABLED",
        "CALLBACK_DELIVERY_ENABLED",
        "LIVE_EMAIL_DELIVERY",
        "LIVE_PSTN_DIALING",
        "ODOO_DELIVERY_ENABLED",
        "ODOO_RESULT_DELIVERY_ENABLED",
        "ODOO_WRITE_ENABLED",
        "ODOO_AUTOMATION_WRITES_ENABLED",
    ):
        assert f'{setting}: "false"' in DEPLOYMENT
