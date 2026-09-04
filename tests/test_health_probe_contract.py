import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_websocket_gateway_uses_canonical_middleware_health_probe() -> None:
    application = (ROOT / "websocket_gateway" / "app.py").read_text(encoding="utf-8")
    compose = (ROOT / "websocket_gateway" / "compose.yaml").read_text(encoding="utf-8")

    canonical_probe = "http://middleware:8095/healthz"
    stale_probe = re.compile(r"http://middleware:8095/health(?=[\s\"'])")

    assert canonical_probe in application
    assert canonical_probe in compose
    assert stale_probe.search(application) is None
    assert stale_probe.search(compose) is None
