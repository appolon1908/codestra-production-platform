#!/usr/bin/env python3
import json
from pathlib import Path

root = Path(__file__).parents[1]
manifest = json.loads((root / "manifests/campaign-crm-workflow-manifest.json").read_text())
assert manifest["workflow_count"] == len(manifest["workflows"])
assert manifest["workflow_count"] >= 75
for item in manifest["workflows"]:
    workflow = json.loads((root / item["path"]).read_text())
    assert workflow["id"] == item["id"] and workflow["active"] is False
    assert workflow["meta"]["middleware_only"] is True
    assert workflow["meta"]["kong_only"] is True
    assert workflow["meta"]["direct_database_access"] is False
    encoded = json.dumps(workflow).lower()
    assert "postgres" not in encoded and "mysql" not in encoded
    assert "$env" not in encoded
    assert "/api/v1/integrations/n8n/results" in encoded
    assert not any(node["type"] in {"n8n-nodes-base.postgres", "n8n-nodes-base.mySql"} for node in workflow["nodes"])
    requests = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequest"]
    assert len(requests) == 2
    for request in requests:
        assert request["parameters"]["url"].startswith("https://api.codestra.co/api/v1/")
        assert request["parameters"]["authentication"] == "genericCredentialType"
        assert request["parameters"]["genericAuthType"] == "oAuth2Api"
        assert request["credentials"]["oAuth2Api"]["id"] == "codestraN8nCommunicationsOAuth"
print(f"campaign CRM catalog: PASS ({manifest['workflow_count']} inactive workflows)")
