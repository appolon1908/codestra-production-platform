import pytest

from control_plane_service.campaign_gates import authorize_campaign_email, authorize_channel
from control_plane_service.core import ControlPlaneError


def canary_environment(monkeypatch):
    monkeypatch.setenv("CAMPAIGN_SCOPED_CHANNEL_GATES_ENABLED", "true")
    monkeypatch.setenv("COD_WEB_OUT_EMAIL_ENABLED", "true")
    monkeypatch.setenv("COD_WEB_OUT_EMAIL_MODE", "CANARY")
    monkeypatch.setenv("COD_WEB_OUT_EMAIL_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("GLOBAL_EMAIL_PRODUCTION", "false")
    monkeypatch.setenv("SMS_PRODUCTION", "false")


def test_empty_recipient_slot_allows_only_no_submit_simulation(monkeypatch):
    canary_environment(monkeypatch)
    monkeypatch.delenv("COD_WEB_OUT_CANARY_RECIPIENT", raising=False)
    authorize_campaign_email({"campaign_id":"COD-WEB-OUT", "tenant_id":"COD", "external_submission":False}, simulation=True)
    with pytest.raises(ControlPlaneError, match="canary_recipient_denied"):
        authorize_campaign_email({"campaign_id":"COD-WEB-OUT", "tenant_id":"COD", "recipient":"person@example.invalid"})


def test_exact_allowlist_and_campaign_isolation(monkeypatch):
    canary_environment(monkeypatch)
    monkeypatch.setenv("COD_WEB_OUT_CANARY_RECIPIENT", "approved@example.invalid")
    authorize_campaign_email({"campaign_id":"COD-WEB-OUT", "tenant_id":"COD", "business_unit_id":"COD", "recipient":"approved@example.invalid"})
    for value in (
        {"campaign_id":"COD-WEB-OUT", "tenant_id":"COD", "recipient":"other@example.invalid"},
        {"campaign_id":"COD-WEB-OUT", "tenant_id":"OTHER", "recipient":"approved@example.invalid"},
        {"campaign_id":"COD-WEB-OUT", "tenant_id":"COD", "business_unit_id":"OTHER", "recipient":"approved@example.invalid"},
        {"campaign_id":"COD-TEST-OUT", "recipient":"approved@example.invalid"},
    ):
        with pytest.raises(ControlPlaneError):
            authorize_campaign_email(value)


def test_sms_remains_disabled(monkeypatch):
    canary_environment(monkeypatch)
    with pytest.raises(ControlPlaneError, match="sms_production_disabled"):
        authorize_channel({"channel":"sms", "campaign_id":"COD-WEB-OUT"})
