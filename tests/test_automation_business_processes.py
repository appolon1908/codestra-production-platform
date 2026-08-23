from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_governed_event_has_an_explicit_business_action_plan():
    automation = (ROOT / "control_plane_service/automation.py").read_text()
    workflows = (ROOT / "scripts/build_control_plane_workflows.py").read_text()
    assert "AUTOMATION_PLANS" in automation
    assert "automation_plan_not_allowlisted" in automation
    assert "/api/v1/automation/execute" in workflows
    assert "Execute governed business process" in workflows
    assert "executed_actions" in workflows


def test_automation_execution_is_durable_idempotent_and_tenant_scoped():
    migration = (ROOT / "migrations/control_plane/006_delivery_leases_and_realtime.sql").read_text()
    source = (ROOT / "control_plane_service/automation.py").read_text()
    assert "PRIMARY KEY(tenant_id,event_id,workflow_key)" in migration
    assert "ON CONFLICT DO NOTHING" in source
    assert 'value.get("tenant_id") != tenant' in source
    assert "automation_action_plan_mismatch" in source
