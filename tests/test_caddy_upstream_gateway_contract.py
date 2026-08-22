from pathlib import Path

import yaml


SOURCE = Path("deploy/caddy-upstream-gateway/api-kong.caddy").read_text()
COMPOSE = yaml.safe_load(Path("deploy/caddy-upstream-gateway/compose.yaml").read_text())


def test_private_gateway_preserves_canonical_https_scheme():
    assert "reverse_proxy codestra-kong-kong-gateway-1:8000" in SOURCE
    assert "header_up X-Forwarded-Proto https" in SOURCE


def test_private_gateway_is_managed_and_host_loopback_only():
    service = COMPOSE["services"]["api-kong-upstream"]
    assert service["restart"] == "unless-stopped"
    assert service["ports"] == ["127.0.0.1:18101:18101"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert COMPOSE["networks"]["edge"]["name"] == "codestra_edge"
