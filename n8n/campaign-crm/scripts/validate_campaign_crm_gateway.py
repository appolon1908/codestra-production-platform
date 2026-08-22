#!/usr/bin/env python3
"""Fail closed unless every campaign CRM HTTP call uses managed OAuth via Kong."""
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = json.loads((ROOT / "manifests/campaign-crm-workflow-manifest.json").read_text())

assert MANIFEST["workflow_count"] == 75
for entry in MANIFEST["workflows"]:
    workflow = json.loads((ROOT / entry["path"]).read_text())
    assert workflow["active"] is False
    assert workflow["meta"]["kong_only"] is True
    assert workflow["meta"]["oauth_client"] == "codestra-n8n-communications"
    for node in workflow["nodes"]:
        if node["type"] != "n8n-nodes-base.httpRequest":
            continue
        assert node["typeVersion"] >= 4.2
        parameters = node["parameters"]
        assert parameters["url"].startswith("https://api.codestra.co/api/v1/")
        assert "middleware" not in parameters["url"].lower()
        assert parameters["genericAuthType"] == "oAuth2Api"
        credential = node["credentials"]["oAuth2Api"]
        assert credential["id"] == "codestraN8nCommunicationsOAuth"
        assert credential["name"] == "Codestra n8n Communications OAuth"

print("validated 75 inactive OAuth/Kong-only campaign CRM workflows")
