import json
from pathlib import Path


IDENTITY = json.loads(Path("config/keycloak-odoo-callback-client.json").read_text())
KONG = json.loads(Path("config/kong-callback-routes.json").read_text())
RECONCILER = Path("scripts/reconcile_kong_callback_routes.py").read_text()
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
    assert set(client["optionalClientScopes"]) == {"callbacks.read", "callbacks.write"}
    assert IDENTITY["serviceAccountRealmRoles"] == ["service"]
    assert IDENTITY["delivery"]["syntheticOnly"] is True
    serialized = json.dumps(IDENTITY)
    assert '"clientSecret"' not in serialized
    assert '"secretValue"' not in serialized
    assert IDENTITY["delivery"]["secretInSource"] is False


def test_identity_claims_are_exactly_cod_test_syn_and_callback_audience():
    mappers = {item["name"]: item for item in IDENTITY["client"]["protocolMappers"]}
    assert mappers["callback-api-audience"]["config"]["included.client.audience"] == "codestra-callback-api"
    assert mappers["callback-tenant"]["config"]["claim.value"] == "COD"
    assert json.loads(mappers["callback-campaigns"]["config"]["claim.value"]) == ["TEST_SYN"]
    roles = mappers["callback-service-realm-roles"]
    assert roles["protocolMapper"] == "oidc-usermodel-realm-role-mapper"
    assert roles["config"]["claim.name"] == "realm_access.roles"
    assert roles["config"]["access.token.claim"] == "true"


def test_kong_exposes_only_required_callback_surfaces():
    assert KONG["host"] == "api.codestra.co"
    assert KONG["service"]["host"] == "codestra-middleware-integration-api-1"
    assert KONG["service"]["port"] == 8095
    assert {path for route in KONG["routes"] for path in route["paths"]} == {
        "/api/v1/control/callbacks", "/api/v1/callbacks"
    }
    assert {method for route in KONG["routes"] for method in route["methods"]} <= {"GET", "POST"}
    assert all(route["maxBodyMb"] == 1 and route["ratePerMinute"] > 0 for route in KONG["routes"])
    assert {route["requiredScope"] for route in KONG["routes"]} == {"callbacks.read", "callbacks.write"}
    assert 'parser.add_argument("--apply", action="store_true")' in RECONCILER
    assert "duplicate Kong" in RECONCILER
    assert "correlation-id" in RECONCILER
    assert "openid-connect" in RECONCILER
    assert "verify_service" in RECONCILER
    assert "verify_route" in RECONCILER
    assert "verify_plugins" in RECONCILER
    assert "select_managed_route" in RECONCILER
    assert "conflicting live route" in RECONCILER
    assert "partial legacy route overlap" in RECONCILER
    assert "all_rows" in RECONCILER
    assert '"request-termination"' in RECONCILER
    assert '"config.status_code": 503' in RECONCILER
    assert "request_json" in RECONCILER
    assert 'route.get("headers") or {}' in RECONCILER
    assert "callback route has an enabled deny plugin" in RECONCILER
    assert "audience_required" in RECONCILER
    assert "bearer_token_param_type" in RECONCILER
    assert 'parser.add_argument("--evidence", type=Path, required=True)' in RECONCILER
    assert "manifest_sha256" in RECONCILER
    assert 'name == "openid-connect" and current' in RECONCILER
    assert "if oidc_matches(current, expected, spec):" in RECONCILER
    assert "needs_quarantine" in RECONCILER
    assert "callback-route-disabled.invalid" in RECONCILER
    assert 'correlation.get("echo_downstream"), True' in RECONCILER
    assert 'rate.get("limit_by"), "ip"' in RECONCILER


def test_deployment_keeps_every_broad_delivery_path_disabled():
    assert 'CODESTRA_CALLBACK_SYNC_ENABLED: "true"' in DEPLOYMENT
    assert "codestra-odoo-callback-service" in DEPLOYMENT
    assert "exact reviewed addon release required" in DEPLOYMENT
    for setting in (
        "CALLBACK_EMAIL_COMMAND_ENABLED", "CALLBACK_DELIVERY_ENABLED",
        "LIVE_EMAIL_DELIVERY", "LIVE_PSTN_DIALING", "ODOO_DELIVERY_ENABLED",
        "ODOO_RESULT_DELIVERY_ENABLED", "ODOO_WRITE_ENABLED",
        "ODOO_AUTOMATION_WRITES_ENABLED",
    ):
        assert f'{setting}: "false"' in DEPLOYMENT
