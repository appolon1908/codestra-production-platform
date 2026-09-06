from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readiness_evidence_uses_canonical_middleware_probes() -> None:
    contract = (ROOT / "docs" / "MIDDLEWARE_PLATFORM_CONTRACT.md").read_text(
        encoding="utf-8"
    )
    report = (
        ROOT
        / "reports"
        / "app-server-a"
        / "PRODUCTION_CALLING_READINESS_20260904.md"
    ).read_text(encoding="utf-8")
    gateway_override = (
        ROOT
        / "deploy"
        / "architecture-remediation"
        / "compose.websocket-gateway.yaml"
    ).read_text(encoding="utf-8")

    assert "`GET /livez`" in contract
    assert "`GET /readyz`" in contract
    assert "200 http://127.0.0.1:8095/healthz" in report
    assert "200 http://127.0.0.1:8095/readyz" in report
    assert "200 http://127.0.0.1:8095/livez" in report
    assert "false alarm caused by diagnostic path mismatch" in report
    assert (
        "INTERNAL_EVENT_SOURCE_HEALTH_URL: http://middleware:8095/healthz"
        in gateway_override
    )
