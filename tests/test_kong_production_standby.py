import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "deploy" / "kong-production-standby"


def data(name):
    return json.loads((PACKAGE / name).read_text())


def test_detached_and_provider_safe():
    config = data("kong/standby.json")
    assert config["publicRoutesEnabled"] is False
    assert config["stagingHostname"] != config["publicHostname"]
    assert all(item["upstream"].startswith("no-delivery-middleware-fixture:") for item in config["services"])


def test_scraper_and_telephony_absent():
    config = data("kong/standby.json")
    paths = {item["path"] for item in config["services"]}
    assert not any(path.startswith("/v1/scraper") or path.startswith("/v1/telephony") for path in paths)
    assert all(not gate["routeCreated"] for gate in config["gatedRouteFamilies"].values())


def test_resource_client_has_no_browser_or_machine_flow():
    client = data("keycloak/codestra-api.json")
    assert client["bearerOnly"] is True
    assert client["redirectUris"] == []
    assert client["webOrigins"] == []
    assert client["standardFlowEnabled"] is False
    assert client["implicitFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert client["serviceAccountsEnabled"] is False


def test_required_scope_catalog_exact():
    scopes = set(data("keycloak/scopes.json")["scopes"])
    assert scopes == {
        "sms.send", "sms.read", "sms.bulk", "email.send", "email.read", "email.bulk",
        "scraper.submit", "scraper.read", "telephony.read", "telephony.control",
        "webhooks.sms.ingest", "webhooks.email.ingest",
    }


def test_no_native_protocol_upstream():
    config = data("kong/standby.json")
    forbidden = set(config["nativeProtocolPortsExcluded"])
    assert all(int(item["upstream"].rsplit(":", 1)[1]) not in forbidden for item in config["services"])
