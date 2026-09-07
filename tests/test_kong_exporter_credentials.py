"""Offline regressions for credentials in exported Kong plugin evidence."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kong_exporter_credentials_under_test",
    ROOT / "scripts/export_kong_public_route_contracts.py",
)
assert SPEC is not None and SPEC.loader is not None
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)


@pytest.mark.parametrize("key", ["provision_key", "PROVISION_KEY", "Provision-Key"])
def test_oauth_provision_key_is_opaque_redaction(key):
    # Synthetic low-entropy value: its unsalted digest must not be published either.
    secret = "synthetic-pin-4711"
    result = EXPORTER.sanitize({"oauth2": [{key: secret, "scopes": ["read"]}]})
    assert result == {"oauth2": [{key: {"redacted": True}, "scopes": ["read"]}]}
    encoded = json.dumps(result)
    assert secret not in encoded
    assert hashlib.sha256(secret.encode()).hexdigest() not in encoded


def test_oauth_provision_key_in_url_is_redacted():
    assert EXPORTER.sanitize(
        "https://example.invalid/oauth?provision_key=synthetic-pin-4711"
    ) == {"redacted": True}


def test_route_evidence_never_contains_oauth_provision_key(monkeypatch):
    secret = "synthetic-pin-4711"
    monkeypatch.setattr(EXPORTER, "all_rows", lambda *_args: [{
        "name": "oauth2", "enabled": True,
        "config": {"provision_key": secret, "scopes": ["read"], "mandatory_scope": True},
    }])
    result = EXPORTER.route_record(
        "http://example.invalid:8001",
        {"id": "route-id", "name": "test-route", "service": {"id": "service-id"}},
        {"service-id": {"name": "test-service", "protocol": "http", "host": "example.invalid", "port": 80}},
    )
    plugin = result["plugins"][0]
    assert plugin["config"]["provision_key"] == {"redacted": True}
    assert plugin["config"]["scopes"] == ["read"]
    assert plugin["config"]["mandatory_scope"] is True
    assert plugin["sanitized_config_sha256"] == EXPORTER.canonical_sha256(plugin["config"])
    encoded = json.dumps(result)
    assert secret not in encoded
    assert hashlib.sha256(secret.encode()).hexdigest() not in encoded
