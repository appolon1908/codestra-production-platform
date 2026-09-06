from pathlib import Path


SOURCE = Path("operations/caddy/api.codestra.co.caddy").read_text()


def test_realtime_transport_remains_outside_public_kong_routes():
    assert "@realtime path /ws/agent" in SOURCE
    assert "@realtime_meta path /healthz /readyz /version" in SOURCE
    assert "/api/v1/realtime/sessions" not in SOURCE.split("handle @realtime", 1)[0]
    assert "reverse_proxy 127.0.0.1:18102" in SOURCE
    assert "reverse_proxy 127.0.0.1:18103" in SOURCE


def test_realtime_ticket_creation_falls_through_to_middleware():
    assert "handle {\n\t\treverse_proxy 127.0.0.1:18101" in SOURCE
    assert "Realtime ticket creation remains a POST owned by" in SOURCE


def test_canonical_log_filter_removes_credentials():
    assert "request>headers>Authorization delete" in SOURCE
    assert "request>headers>X-Api-Key delete" in SOURCE
