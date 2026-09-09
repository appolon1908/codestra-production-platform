import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_migration_installs_complete_graph_and_forces_inactive(tmp_path):
    generated = json.loads(
        subprocess.check_output(
            ["python3", str(ROOT / "scripts/build_control_plane_workflows.py")]
        )
    )
    current = []
    for item in generated:
        clone = json.loads(json.dumps(item))
        clone["active"] = item["id"] != "CodestraCP90"
        clone["nodes"] = clone["nodes"][:2]
        clone["connections"] = {}
        clone["staticData"] = {"global": {"seen": {"old": "mapping"}}}
        current.append(clone)
    source = tmp_path / "current.json"
    templates = tmp_path / "generated.json"
    output = tmp_path / "out.json"
    source.write_text(json.dumps(current))
    templates.write_text(json.dumps(generated))
    subprocess.check_call(
        [
            "python3",
            str(ROOT / "scripts/migrate_n8n_stateless.py"),
            str(source),
            str(templates),
            str(output),
        ]
    )
    migrated = json.loads(output.read_text())
    by_id = {item["id"]: item for item in generated}
    assert all(item["active"] is False for item in migrated)
    assert all(item.get("staticData") is None for item in migrated)
    assert all(item["nodes"] == by_id[item["id"]]["nodes"] for item in migrated)
    assert all(item["connections"] == by_id[item["id"]]["connections"] for item in migrated)
    assert "$getWorkflowStaticData" not in json.dumps(migrated)
