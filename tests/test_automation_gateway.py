import json

from control_plane_service.automation import (
    authorize_automation,
    execute_automation,
    record_execution_result,
)
from control_plane_service.core import ControlPlaneError, Store


def envelope():
    return {"schema_version":"1", "event_id":"evt-1", "event_type":"crm.followup.due.v1",
            "correlation_id":"corr-1", "idempotency_key":"idem-1", "tenant_id":"COD",
            "business_unit_id":"COD", "campaign_id":"TEST_SYN", "entity_type":"crm.lead",
            "entity_id":"lead-1", "actor_type":"SYSTEM", "actor_id":"middleware",
            "occurred_at":"2026-08-22T00:00:00Z", "automation_key":"test_syn_followup",
            "orchestration_execution_id":"exec-1", "payload":{}}


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


def test_result_is_durable_and_idempotent(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "control-plane.db"))
    secret = tmp_path / "action-secret"
    secret.write_bytes(b"test-only-action-secret-material-32-bytes")
    monkeypatch.setenv("CONTROL_PLANE_AUTOMATION_ACTION_SECRET_FILE", str(secret))
    monkeypatch.setenv(
        "CONTROL_PLANE_ACTION_CAMPAIGN_FOLLOWUP_EXECUTE_URL",
        "http://middleware-handler.test/followup",
    )
    calls = []

    class Response:
        status = 200

        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self):
            request = calls[-1]
            body = json.loads(request.data)
            return json.dumps({
                "status": "COMPLETED",
                "action": body["action"],
                "idempotency_key": body["idempotency_key"],
            }).encode()

    def invoke(request, timeout):
        assert timeout == 10
        calls.append(request)
        return Response()

    monkeypatch.setattr("control_plane_service.automation.urllib.request.urlopen", invoke)
    authorized = authorize_automation(store, envelope(), "COD")
    execution = execute_automation(store, authorized, "COD")
    replay = execute_automation(store, authorized, "COD")
    assert execution["business_process_status"] == "ACTIONS_COMPLETED"
    assert replay["executed_actions"] == execution["executed_actions"]
    assert len(calls) == 1
    result = {"event_id":"evt-1", "correlation_id":"corr-1", "idempotency_key":"result-1",
              "workflow_key":"test_syn_followup", "execution_id":"exec-1", "status":"COMPLETED",
              "actions":[{"type":"campaign.followup.execute"}], "completed_at":"2026-08-22T00:00:01Z"}
    first = record_execution_result(store, result, "COD")
    second = record_execution_result(store, result, "COD")
    assert first.duplicate is False and second.duplicate is True


def test_missing_action_handler_cannot_be_reported_complete(tmp_path):
    store = Store(str(tmp_path / "control-plane.db"))
    authorized = authorize_automation(store, envelope(), "COD")
    try:
        execute_automation(store, authorized, "COD")
    except ControlPlaneError as exc:
        assert str(exc) == "automation_action_handler_missing:campaign.followup.execute"
    else:
        raise AssertionError("missing business action handler was accepted")
    result = {"event_id":"evt-1", "correlation_id":"corr-1", "idempotency_key":"result-1",
              "workflow_key":"test_syn_followup", "execution_id":"exec-1", "status":"COMPLETED",
              "actions":[{"type":"campaign.followup.execute"}], "completed_at":"2026-08-22T00:00:01Z"}
    try:
        record_execution_result(store, result, "COD")
    except ControlPlaneError as exc:
        assert str(exc) == "automation_actions_incomplete"
    else:
        raise AssertionError("incomplete business action was reported complete")


def test_failure_callback_resolves_original_identity_from_n8n_execution(tmp_path):
    store = Store(str(tmp_path / "control-plane.db"))
    authorized = authorize_automation(store, envelope(), "COD")
    try:
        execute_automation(store, authorized, "COD")
    except ControlPlaneError as exc:
        assert "automation_action_handler_missing" in str(exc)
    failure = {
        "event_id":"resolve-from-execution", "correlation_id":"resolve-from-execution",
        "idempotency_key":"n8n-failure:exec-1", "workflow_key":"resolve-from-execution",
        "execution_id":"exec-1", "status":"FAILED", "actions":[],
        "completed_at":"2026-08-22T00:00:01Z",
    }
    result = record_execution_result(store, failure, "unknown")
    assert result.event_id == "n8n-result-evt-1"
    with store.connect() as db:
        row = db.execute(
            "SELECT status,event_id,workflow_key,correlation_id FROM automation_executions "
            "WHERE execution_id='exec-1'"
        ).fetchone()
    assert dict(row) == {
        "status":"FAILED", "event_id":"evt-1", "workflow_key":"test_syn_followup",
        "correlation_id":"corr-1",
    }


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
