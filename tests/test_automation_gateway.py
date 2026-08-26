from control_plane_service.automation import authorize_automation, record_execution_result
from control_plane_service.core import ControlPlaneError, Store


def envelope():
    return {"schema_version":"1", "event_id":"evt-1", "event_type":"crm.followup.due.v1",
            "correlation_id":"corr-1", "idempotency_key":"idem-1", "tenant_id":"COD",
            "business_unit_id":"COD", "campaign_id":"TEST_SYN", "entity_type":"crm.lead",
            "entity_id":"lead-1", "actor_type":"SYSTEM", "actor_id":"middleware",
            "occurred_at":"2026-08-22T00:00:00Z", "automation_key":"test_syn_followup", "payload":{}}


def test_policy_is_tenant_bound_and_fail_closed_for_communications(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPAIGN_SCOPED_CHANNEL_GATES_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_EMAIL_PRODUCTION", "true")
    store = Store(str(tmp_path / "control-plane.db"))
    assert authorize_automation(store, envelope(), "COD")["authorized"] is True
    wrong = envelope(); wrong["tenant_id"] = "OTHER"
    try: authorize_automation(store, wrong, "COD")
    except ControlPlaneError as exc: assert str(exc) == "cross_tenant_denied"
    else: raise AssertionError("cross-tenant automation allowed")
    denied = envelope(); denied["payload"] = {"channel":"email", "contact_id":"contact-1"}
    try: authorize_automation(store, denied, "COD")
    except ControlPlaneError as exc: assert str(exc) == "contact_policy_denied"
    else: raise AssertionError("communication without consent allowed")
    store.set_preference("COD", "contact-1", "email", "subscribed", "TEST_SYN")
    assert authorize_automation(store, denied, "COD")["authorized"] is True


def test_result_is_durable_and_idempotent(tmp_path):
    store = Store(str(tmp_path / "control-plane.db"))
    result = {"event_id":"evt-1", "correlation_id":"corr-1", "idempotency_key":"result-1",
              "workflow_key":"test_syn_followup", "execution_id":"exec-1", "status":"COMPLETED",
              "actions":[], "completed_at":"2026-08-22T00:00:01Z"}
    first = record_execution_result(store, result, "COD")
    second = record_execution_result(store, result, "COD")
    assert first.duplicate is False and second.duplicate is True


def test_cod_web_out_email_requires_exact_contact_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPAIGN_SCOPED_CHANNEL_GATES_ENABLED", "true")
    monkeypatch.setenv("COD_WEB_OUT_EMAIL_ENABLED", "true")
    monkeypatch.setenv("COD_WEB_OUT_EMAIL_MODE", "CANARY")
    monkeypatch.setenv("COD_WEB_OUT_EMAIL_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("COD_WEB_OUT_CANARY_RECIPIENT", "appolon@codestra.co")
    store = Store(str(tmp_path / "control-plane.db"))
    store.set_preference("COD", "internal-canary", "email", "subscribed", "internal_test")
    value = envelope()
    value["campaign_id"] = "COD-WEB-OUT"
    value["payload"] = {
        "channel":"email", "contact_id":"internal-canary", "recipient":"appolon@codestra.co",
        "sender":"sales@codestra.co", "reply_to":"support@codestra.co", "country":"DO",
        "legal_basis":"internal_test", "classification":"transactional",
    }
    assert authorize_automation(store, value, "COD")["authorized"] is True
    for field in ("country", "legal_basis"):
        denied = {**value, "payload":{**value["payload"]}}
        denied["payload"].pop(field)
        try: authorize_automation(store, denied, "COD")
        except ControlPlaneError as exc: assert str(exc) == "contact_policy_denied"
        else: raise AssertionError(f"missing {field} was allowed")
    held = {**value, "payload":{**value["payload"], "campaign_hold":True}}
    try: authorize_automation(store, held, "COD")
    except ControlPlaneError as exc: assert str(exc) == "contact_policy_denied"
    else: raise AssertionError("held contact was allowed")
