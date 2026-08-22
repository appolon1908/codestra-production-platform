import json, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def workflows():
    return json.loads(subprocess.check_output(["python3",str(ROOT/"scripts/build_mapping_workflows.py")]))

def test_workflows_are_modular_inactive_and_stateless():
    items=workflows()
    assert len(items)==15 and len({x["name"] for x in items})==15
    raw=json.dumps(items)
    assert all(not x["active"] for x in items)
    assert "$getWorkflowStaticData" not in raw
    assert "VICIDIAL" not in raw or "direct SQL" not in raw
    assert "/api/v1/control/adapters/execute" in raw
    assert "/api/v1/results/jobs/" in raw

def test_contract_preserves_required_envelope_fields():
    code="\n".join(n.get("parameters",{}).get("jsCode","") for w in workflows() for n in w["nodes"])
    for field in ("schema_version","event_id","correlation_id","idempotency_key","entity_version","event_kind"):
        assert field in code
    assert "EXECUTED_NOT_VERIFIED" in code
    assert "payload.job_id" in code
