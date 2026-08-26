import json,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_migration_preserves_activation_and_removes_static_authority(tmp_path):
    generated=json.loads(subprocess.check_output(["python3",str(ROOT/"scripts/build_control_plane_workflows.py")]))
    current=[]
    for item in generated:
        clone=json.loads(json.dumps(item)); clone["active"]=item["id"]!="CodestraCP90"
        clone["staticData"]={"global":{"seen":{"old":"mapping"}}}; current.append(clone)
    source=tmp_path/"current.json"; templates=tmp_path/"generated.json"; output=tmp_path/"out.json"
    source.write_text(json.dumps(current)); templates.write_text(json.dumps(generated))
    subprocess.check_call(["python3",str(ROOT/"scripts/migrate_n8n_stateless.py"),str(source),str(templates),str(output)])
    migrated=json.loads(output.read_text())
    assert sum(x["active"] for x in migrated)==len(generated)-1
    assert all(x.get("staticData") is None for x in migrated if x["id"]!="CodestraCP90")
    assert "$getWorkflowStaticData" not in json.dumps(migrated)
