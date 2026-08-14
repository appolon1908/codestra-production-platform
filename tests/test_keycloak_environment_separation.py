from pathlib import Path


def parse(path: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in Path(path).read_text().splitlines()
        if line and not line.startswith("#")
    )


def test_keycloak_environments_have_distinct_contracts() -> None:
    production = parse("config/keycloak-production-contract.env.example")
    staging = parse("config/keycloak-staging-contract.env.example")
    for field in ("KEYCLOAK_ISSUER", "KEYCLOAK_AUDIENCE", "KEYCLOAK_CLIENT_ID", "KEYCLOAK_CLIENT_SECRET_FILE"):
        assert production[field] != staging[field]
    assert production["KEYCLOAK_CLIENT_ID"].endswith("-production")
    assert staging["STAGING_ONLY"] == "true"
    assert staging["PRODUCTION_DELIVERY_ALLOWED"] == "false"
    assert production["PROVISIONING_SERVICE_CLIENT_ID"] != staging["KEYCLOAK_CLIENT_ID"]


def test_no_secret_value_is_embedded() -> None:
    for path in Path("config").glob("keycloak-*-contract.env.example"):
        values = parse(str(path))
        assert all(not key.endswith("SECRET") for key in values)
        assert all("SECRET_FILE" in key for key in values if "SECRET" in key)
