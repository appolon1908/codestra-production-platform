from pathlib import Path


KONG = Path("deploy/kong/control-plane.yml").read_text()


def test_automation_gateway_uses_canonical_production_control_plane():
    assert "http://codestra-integration-control-plane-api-1:8096" in KONG
    assert "http://codestra-control-plane:8096" not in KONG
