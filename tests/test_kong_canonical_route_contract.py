import json
from pathlib import Path


MANIFEST = json.loads(Path("config/kong-canonical-middleware-routes.json").read_text())
SOURCE = Path("scripts/reconcile_kong_canonical_routes.py").read_text()


def test_only_proven_middleware_routes_are_public():
    assert {route["path"] for route in MANIFEST["routes"]} == {
        "/v1/crm", "/v1/email", "/v1/sms", "/v1/webhooks", "/v1/sms/dlr/telnexa",
    }


def test_every_route_has_explicit_security_controls():
    for route in MANIFEST["routes"]:
        assert route["methods"]
        assert route["auth"] == "key-auth"
        assert route["maxBodyMb"] > 0
        assert route["ratePerMinute"] > 0


def test_reconciler_is_dry_run_by_default_and_fail_closed():
    assert 'parser.add_argument("--apply", action="store_true")' in SOURCE
    assert "expected exactly one existing route" in SOURCE
    assert "required auth plugin absent" in SOURCE
    assert "limiter readback mismatch" in SOURCE
    assert "unexpected_public" in SOURCE


def test_every_additional_public_route_has_an_owner_and_source():
    owned = MANIFEST["ownedProductionRoutes"]
    assert len(owned) == 9
    assert len({route["name"] for route in owned}) == 9
    for route in owned:
        assert route["classification"] == "REQUIRED_PRODUCTION"
        assert route["owner"]
        assert route["source"]
    assert "ownedProductionRoutes" in SOURCE
