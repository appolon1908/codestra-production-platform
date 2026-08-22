import json
from pathlib import Path


def parse_env(path: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in Path(path).read_text().splitlines()
        if line and not line.startswith("#")
    )


CONTRACT_PATH = "config/keycloak-webphone-machine-contract.env.example"
SPEC_PATH = "config/keycloak-webphone-machine-client.json"


def test_canonical_machine_identity_matches_consumer_contract() -> None:
    contract = parse_env(CONTRACT_PATH)
    assert contract["KEYCLOAK_ISSUER"] == "https://auth.codestra.co/realms/codestra"
    assert contract["KEYCLOAK_CLIENT_ID"] == "codestra-provisioning-service-staging"
    assert contract["KEYCLOAK_PROTOCOL"] == "openid-connect"
    assert contract["KEYCLOAK_PUBLIC_CLIENT"] == "false"
    assert contract["KEYCLOAK_BEARER_ONLY"] == "false"
    assert contract["KEYCLOAK_CLIENT_AUTHENTICATOR_TYPE"] == "client-secret"
    assert contract["KEYCLOAK_CLIENT_AUTH_METHOD"] == "client_secret_post"
    assert contract["KEYCLOAK_EXPECTED_AZP"] == contract["KEYCLOAK_CLIENT_ID"]
    assert contract["KEYCLOAK_AUDIENCE"] == "codestra-provisioning-service"
    assert contract["KEYCLOAK_REQUIRED_SCOPES"].split() == [
        "identity:rotate",
        "provisioning:execute",
        "provisioning:read",
    ]
    assert contract["KEYCLOAK_REQUIRED_REALM_ROLES"] == ""
    assert contract["KEYCLOAK_REQUIRED_CLIENT_ROLES"] == "realm-management:view-users"


def test_machine_client_is_service_account_only_and_short_lived() -> None:
    contract = parse_env(CONTRACT_PATH)
    assert contract["GRANT_TYPE"] == "client_credentials"
    assert contract["SERVICE_ACCOUNTS_ENABLED"] == "true"
    assert contract["STANDARD_FLOW_ENABLED"] == "false"
    assert contract["DIRECT_ACCESS_GRANTS_ENABLED"] == "false"
    assert contract["IMPLICIT_FLOW_ENABLED"] == "false"
    assert contract["FULL_SCOPE_ALLOWED"] == "false"
    assert contract["KEYCLOAK_DEFAULT_CLIENT_SCOPES"] == ""
    assert contract["KEYCLOAK_OPTIONAL_CLIENT_SCOPES"] == ""
    assert int(contract["KEYCLOAK_MAX_TOKEN_TTL_SECONDS"]) <= 300


def test_staging_and_canonical_certification_contracts_remain_separate() -> None:
    canonical = parse_env(CONTRACT_PATH)
    staging = parse_env("config/keycloak-staging-contract.env.example")
    assert canonical["KEYCLOAK_ISSUER"] != staging["KEYCLOAK_ISSUER"]
    assert canonical["KEYCLOAK_AUDIENCE"] != staging["KEYCLOAK_AUDIENCE"]
    assert canonical["KEYCLOAK_CLIENT_SECRET_FILE"] != staging["KEYCLOAK_CLIENT_SECRET_FILE"]
    assert staging["STAGING_ONLY"] == "true"
    assert staging["PRODUCTION_DELIVERY_ALLOWED"] == "false"
    assert canonical["PRODUCTION_DELIVERY_ALLOWED"] == "false"


def test_structured_keycloak_spec_matches_environment_contract() -> None:
    contract = parse_env(CONTRACT_PATH)
    spec = json.loads(Path(SPEC_PATH).read_text())
    client = spec["client"]
    token = spec["tokenContract"]
    assert client["clientId"] == contract["KEYCLOAK_CLIENT_ID"]
    assert client["protocol"] == "openid-connect"
    assert client["publicClient"] is False
    assert client["clientAuthenticatorType"] == "client-secret"
    assert client["serviceAccountsEnabled"] is True
    assert client["standardFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert client["implicitFlowEnabled"] is False
    assert client["fullScopeAllowed"] is False
    assert client["defaultClientScopes"] == []
    assert client["optionalClientScopes"] == []
    assert token["issuer"] == contract["KEYCLOAK_ISSUER"]
    assert token["audience"] == contract["KEYCLOAK_AUDIENCE"]
    assert token["authorizedParty"] == contract["KEYCLOAK_EXPECTED_AZP"]
    assert token["requiredScopes"] == contract["KEYCLOAK_REQUIRED_SCOPES"].split()
    assert token["maximumLifetimeSeconds"] <= 300
    assert token["singleUseJti"] is True


def test_tenant_boundary_is_explicit_and_not_delegated_to_machine_token() -> None:
    contract = parse_env(CONTRACT_PATH)
    tenants = json.loads(Path("config/keycloak-webphone-allowed-tenants.json").read_text())
    spec = json.loads(Path(SPEC_PATH).read_text())
    assert contract["TENANT_BINDING_REQUIRED"] == "true"
    assert contract["KEYCLOAK_TENANT_MAPPER_REQUIRED"] == "false"
    assert contract["TENANT_BINDING_AUTHORITY"] == "canonical-browser-subject-and-odoo-identity-lookup"
    assert spec["tenantBinding"]["required"] is True
    assert spec["tenantBinding"]["machineTokenClaimRequired"] is False
    assert tenants == {
        "tenants": ["COD"],
        "campaigns": ["TEST_SYN"],
        "extensions": ["6101"],
        "production": False,
    }


def test_protocol_mappers_are_exact_and_no_secret_is_embedded() -> None:
    spec = json.loads(Path(SPEC_PATH).read_text())
    mappers = spec["client"]["protocolMappers"]
    assert [mapper["protocolMapper"] for mapper in mappers] == [
        "oidc-audience-mapper",
        "oidc-hardcoded-claim-mapper",
    ]
    serialized = json.dumps(spec).lower()
    assert "clientsecret" not in serialized
    assert "secretvalue" not in serialized
    assert spec["delivery"]["secretInSource"] is False
