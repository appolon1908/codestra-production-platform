from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEALTH = ROOT / "odoo_addons/codestra_middleware_bridge/controllers/health.py"


def test_odoo_health_contract_is_lightweight_and_sanitized():
    source = HEALTH.read_text()
    for path in ("/codestra/healthz", "/codestra/readyz", "/codestra/version"):
        assert path in source
    assert 'request.env.cr.execute("SELECT 1")' in source
    assert "tools.config.filestore(request.db)" in source
    for forbidden in ("password", "connection_string", "DATABASE_URL"):
        assert forbidden not in source


def test_odoo_health_routes_are_read_only_and_sessionless():
    source = HEALTH.read_text()
    assert source.count('methods=["GET"]') == 3
    assert source.count("save_session=False") == 3
