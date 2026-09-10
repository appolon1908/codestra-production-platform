from pathlib import Path


ROOT = Path(__file__).parents[1]
AUTHORITY = (ROOT / "docs/REALTIME_AUTHORITY.md").read_text()
REALTIME_ADDON = ROOT / "odoo_addons/codestra_crm_call_followup_realtime"


def test_one_gateway_and_one_popup_lease_authority_are_selected() -> None:
    assert (ROOT / "websocket_gateway/app.py").is_file()
    assert (REALTIME_ADDON / "models/realtime_lease.py").is_file()
    assert (REALTIME_ADDON / "static/src/js/post_call_lease_service.js").is_file()

    for competing_path in (
        "models/realtime.py",
        "models/realtime_api.py",
        "static/src/js/post_call_realtime_service.js",
    ):
        assert not (REALTIME_ADDON / competing_path).exists()


def test_authority_is_explicit_and_fail_closed() -> None:
    for required in (
        "Codestra middleware",
        "WebSocket session, ticket, replay, and scoped delivery",
        "Odoo `codestra_crm_call_followup_realtime`",
        "Odoo bus never replaces",
        "one writable PostgreSQL authority",
        "Production remains blocked",
        "No failed gate may be waived",
    ):
        assert required in AUTHORITY


def test_gateway_rejects_browser_command_authority() -> None:
    gateway = (ROOT / "websocket_gateway/app.py").read_text()
    assert '"client_command_not_allowed"' in gateway
    assert "/internal/v1/realtime/events" in gateway
    assert "require_internal" in gateway


def test_popup_submission_is_fenced_by_current_lease() -> None:
    javascript = (REALTIME_ADDON / "static/src/js/post_call_lease_service.js").read_text()
    wizard = (REALTIME_ADDON / "models/post_call_wizard.py").read_text()
    lease = (REALTIME_ADDON / "models/realtime_lease.py").read_text()
    for token in ("default_popup_lease_owner", "default_popup_lease_token"):
        assert token in javascript
    assert "FOR UPDATE" in wizard
    assert "_validate_popup_lease" in wizard
    assert "popup_lease_expires_at <= fields.Datetime.now()" in lease
