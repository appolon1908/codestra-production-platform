import json
import subprocess
import time
from pathlib import Path

from control_plane_service.core import Store, validate_envelope
from control_plane_service import worker


ROOT = Path(__file__).resolve().parents[1]


def workflows():
    return json.loads(subprocess.check_output(["python3", str(ROOT / "scripts/build_control_plane_workflows.py")]))


def test_exact_governed_event_set_and_common_error_workflow():
    items = workflows()
    # One shared error workflow plus the governed communication, customer,
    # crawler, and bounded CRM workflows.
    assert len(items) == 22
    assert items[0]["id"] == "CodestraCP90"
    assert items[0]["nodes"][0]["type"] == "n8n-nodes-base.errorTrigger"
    expected = {
        "telnexa.sms.submitted", "telnexa.sms.sent", "telnexa.sms.received", "telnexa.sms.delivered",
        "telnexa.sms.failed", "telnexa.sms.rejected", "telnexa.sms.expired", "telnexa.sms.opted_out",
        "klyrow.email.delivered", "klyrow.email.bounced", "klyrow.email.deferred", "klyrow.email.complained", "klyrow.email.unsubscribed",
        "kyqra.record.created", "kyqra.job.completed", "kyqra.job.failed", "customer.created", "customer.updated",
        "crm.lead.created", "crm.lead.updated", "crm.activity.created",
    }
    code = "\n".join(node["parameters"].get("jsCode", "") for item in items[1:] for node in item["nodes"])
    assert all(event in code for event in expected)


def test_workflows_are_inactive_authenticated_idempotent_and_context_preserving():
    for item in workflows()[1:]:
        assert item["active"] is False
        assert item["settings"]["errorWorkflow"] == "CodestraCP90"
        assert len(item["nodes"]) == 6
        webhook, validation, authorize, execute, result, callback = item["nodes"]
        assert webhook["parameters"]["authentication"] == "headerAuth"
        assert webhook["credentials"]["httpHeaderAuth"]["id"] == "codestraMiddlewareHeaderAuth"
        code = validation["parameters"]["jsCode"]
        for required in ("correlation_id", "tenant_id", "customer_id", "idempotency_key"):
            assert required in code
        assert "$getWorkflowStaticData" not in code
        assert authorize["type"] == "n8n-nodes-base.httpRequest"
        assert authorize["parameters"]["url"].endswith("/api/v1/automation/authorize")
        assert execute["type"] == "n8n-nodes-base.httpRequest"
        assert execute["parameters"]["url"].endswith("/api/v1/automation/execute")
        assert callback["type"] == "n8n-nodes-base.httpRequest"
        assert callback["parameters"]["url"].endswith("/api/v1/automation/results")
        assert "MIDDLEWARE_INTERNAL_URL" in json.dumps((authorize, execute, callback))
        assert authorize["parameters"]["nodeCredentialType"] == "oAuth2Api"
        assert execute["parameters"]["nodeCredentialType"] == "oAuth2Api"
        assert callback["parameters"]["nodeCredentialType"] == "oAuth2Api"
        assert "10.40.0.4" not in json.dumps(item)
        assert result["name"] == "Build governed completion"
        assert "executed_actions" in result["parameters"]["jsCode"]


def test_manifest_matches_exports_and_contains_no_secrets():
    manifest = json.loads((ROOT / "n8n/control-plane/workflow-manifest.json").read_text())
    assert {w["id"] for w in workflows()} == {w["id"] for w in manifest["workflows"]}
    serialized = json.dumps(workflows())
    assert "CHANGE_ME" not in serialized
    assert "HMAC_SECRET" not in serialized


def test_middleware_timeout_retries_are_bounded_and_end_in_dead_letter(monkeypatch, tmp_path):
    store = Store(str(tmp_path / "control-plane.db"))
    event = validate_envelope({
        "event_type": "customer.created", "event_version": "1.0", "occurred_at": "2026-08-15T00:00:00Z",
        "tenant_id": "tenant", "customer_id": "customer", "correlation_id": "correlation",
        "idempotency_key": "timeout-test", "payload": {"synthetic": True},
    }, "odoo", "timeout-event")
    store.ingest(event)
    monkeypatch.setattr(worker, "store", lambda: store)
    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setenv("CONTROL_PLANE_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("CONTROL_PLANE_N8N_URL", "http://codestra-n8n-1:5678/webhook/codestra-{event_type}")
    monkeypatch.setenv("N8N_OUTBOUND_API_KEY", "test-only-key")
    monkeypatch.setenv("N8N_MIDDLEWARE_HMAC_SECRET", "test-only-secret")
    for attempt in range(1, worker.MAX_ATTEMPTS + 1):
        worker.once()
        with store.connect() as db:
            row = db.execute("SELECT state,attempts FROM event_deliveries WHERE event_id=? AND target='n8n'", (event["event_id"],)).fetchone()
            assert row["attempts"] == attempt
            assert row["state"] == ("dead_letter" if attempt == worker.MAX_ATTEMPTS else "retrying")
            db.execute("UPDATE event_deliveries SET next_attempt=? WHERE event_id=?", (time.time() - 1, event["event_id"]))
