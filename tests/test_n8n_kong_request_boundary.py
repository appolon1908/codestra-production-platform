"""Offline request-boundary regressions; never contact n8n, Kong, or providers."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "workflow_boundary_builder", ROOT / "scripts/build_control_plane_workflows.py"
)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def generated():
    return [BUILDER.error_workflow(), *[BUILDER.event_workflow(*s) for s in BUILDER.SPECS]]


def test_all_generated_requests_use_the_matching_https_authority():
    count = 0
    for workflow in generated():
        assert workflow["active"] is False
        for node in workflow["nodes"]:
            if node["type"] != "n8n-nodes-base.httpRequest":
                continue
            params = node["parameters"]
            url = urlsplit(params["url"].removeprefix("="))
            assert (url.scheme, url.netloc) == ("https", "api.codestra.co")
            assert url.path in {
                "/api/v1/automation/authorize", "/api/v1/automation/execute",
                "/api/v1/automation/results",
            }
            assert params["authentication"] == "predefinedCredentialType"
            assert params["nodeCredentialType"] == "oAuth2Api"
            assert "ignoreResponseCode" not in params["options"]
            assert "allowUnauthorizedCerts" not in params["options"]
            count += 1
    assert count == 64


def test_normal_workflows_keep_explicit_tenant_and_idempotency_headers():
    for workflow in generated()[1:]:
        for node in workflow["nodes"]:
            if node["type"] == "n8n-nodes-base.httpRequest":
                headers = {h["name"]: h["value"] for h in node["parameters"]["headerParameters"]["parameters"]}
                assert headers == {
                    "X-Tenant-ID": "={{$json.tenant_id}}",
                    "Idempotency-Key": "={{$json.idempotency_key}}",
                    "X-Correlation-ID": "={{$json.correlation_id}}",
                }


def test_error_request_uses_verified_oauth_tenant_not_unknown_header():
    callback = BUILDER.error_workflow()["nodes"][-1]
    headers = callback["parameters"]["headerParameters"]["parameters"]
    assert {h["name"] for h in headers} == {"Idempotency-Key", "X-Correlation-ID"}
    assert callback["credentials"]["oAuth2Api"]["id"] == "codestraMiddlewareOAuth2"
    assert "unknown" not in json.dumps(BUILDER.error_workflow())


def run_error_code(payload):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the generated n8n Code node")
    code = BUILDER.error_workflow()["nodes"][1]["parameters"]["jsCode"]
    script = "const c=JSON.parse(process.argv[1]);try{console.log(JSON.stringify({ok:true,result:new Function('$json','$execution',c.code)(c.payload,{id:'error-workflow-id'})}));}catch(e){console.log(JSON.stringify({ok:false,error:e.message}));}"
    output = subprocess.run(
        [node, "-e", script, json.dumps({"code": code, "payload": payload})],
        check=True, capture_output=True, text=True, timeout=5,
    )
    return json.loads(output.stdout)


def test_realistic_error_trigger_keeps_source_execution_without_invented_tenant():
    result = run_error_code({"execution": {"id": "source-123", "error": {"name": "SyntheticError"}}})
    assert result["ok"] is True
    body = result["result"][0]["json"]
    assert body["execution_id"] == "source-123"
    assert body["idempotency_key"] == "n8n-failure:source-123"
    assert "tenant_id" not in body
    assert body["status"] == "FAILED"


@pytest.mark.parametrize("payload", [{}, {"execution": {}}, {"execution": {"id": None}}, {"execution": {"id": " "}}])
def test_error_trigger_missing_source_execution_fails_closed(payload):
    assert run_error_code(payload) == {"ok": False, "error": "source_execution_required"}


def test_untrusted_error_payload_cannot_select_another_tenant():
    result = run_error_code({"tenant_id": "other-tenant", "execution": {"id": "source-123"}})
    assert "tenant_id" not in result["result"][0]["json"]
