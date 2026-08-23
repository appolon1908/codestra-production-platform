from pathlib import Path


SOURCE = Path("operations/caddy/api.codestra.co.caddy").read_text()


def test_realtime_paths_remain_outside_public_kong_routes():
    assert "@realtime path /ws/agent /api/v1/realtime/sessions /healthz /readyz /version" in SOURCE
    assert "reverse_proxy 127.0.0.1:18102" in SOURCE
    assert "handle {\n\t\treverse_proxy 127.0.0.1:18101" in SOURCE


def test_canonical_log_filter_removes_credentials():
    assert "request>headers>Authorization delete" in SOURCE
    assert "request>headers>X-Api-Key delete" in SOURCE
