import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "deploy/kong-production-standby/kong/production-route-hardening.json"


def test_all_routes_are_host_bound_and_https_only():
    routes = json.loads(CONTRACT.read_text())["routes"]
    assert routes
    for name, route in routes.items():
        assert route["hosts"], name
        assert route["protocols"] == ["https"], name


def test_all_routes_have_explicit_methods():
    routes = json.loads(CONTRACT.read_text())["routes"]
    for name, route in routes.items():
        assert route["methods"], name


def test_breero_keeps_application_oidc_and_strips_spoofable_headers():
    route = json.loads(CONTRACT.read_text())["routes"]["breero-production-api-route"]
    assert route["authenticationAuthority"] == "breero-application-oidc"
    assert route["stripSpoofableIdentityHeaders"] is True
