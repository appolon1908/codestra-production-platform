#!/usr/bin/env python3
"""Build inactive, governed n8n imports that call only Middleware APIs."""
from __future__ import annotations

import json
import sys

SPECS = [
    (17, "sms.submitted", "telnexa.sms.submitted"), (18, "sms.sent", "telnexa.sms.sent"),
    (19, "sms.rejected", "telnexa.sms.rejected"), (20, "sms.received", "telnexa.sms.received"),
    (21, "sms.delivered", "telnexa.sms.delivered"), (22, "sms.failed", "telnexa.sms.failed"),
    (23, "sms.opted_out", "telnexa.sms.opted_out"), (24, "email.delivered", "klyrow.email.delivered"),
    (25, "email.bounced", "klyrow.email.bounced"), (26, "email.complained", "klyrow.email.complained"),
    (27, "email.unsubscribed", "klyrow.email.unsubscribed"), (28, "crawler.result.created", "kyqra.record.created"),
    (29, "crawler.job.completed", "kyqra.job.completed"), (30, "crawler.job.failed", "kyqra.job.failed"),
    (31, "customer.created", "customer.created"), (32, "customer.updated", "customer.updated"),
    (33, "email.deferred", "klyrow.email.deferred"), (34, "crm.lead.created", "crm.lead.created"),
    (35, "crm.lead.updated", "crm.lead.updated"), (36, "crm.activity.created", "crm.activity.created"),
    (37, "sms.expired", "telnexa.sms.expired"),
]


def validation_code(name: str, event_type: str) -> str:
    return """const h=$json.headers||{};
const b=$json.body||$json;
if(b.event_type!==EVENT_TYPE) throw new Error('event_type_rejected');
for(const key of ['event_id','correlation_id','tenant_id','idempotency_key']) {
  if(!b[key] && !(key==='event_id' && h['x-event-id'])) throw new Error(key+'_required');
}
const eventId=String(b.event_id||h['x-event-id']);
return [{json:{...b,event_id:eventId,customer_id:String(b.customer_id||b.entity_id||eventId),workflow_key:WORKFLOW,orchestration_execution_id:String($execution.id),actor_type:'SYSTEM',actor_id:'n8n',schema_version:'1',business_unit_id:String(b.business_unit_id||'default'),campaign_id:String(b.campaign_id||'none'),entity_type:String(b.entity_type||'event'),entity_id:String(b.entity_id||eventId),automation_key:String(b.automation_key||WORKFLOW),payload:b.payload||{}}}];
""".replace("EVENT_TYPE", json.dumps(event_type)).replace("WORKFLOW", json.dumps(name))


def result_code() -> str:
    return """const b=$json;
if(b.business_process_status!=='ACTIONS_COMPLETED') throw new Error('business_actions_incomplete');
return [{json:{event_id:b.event_id,correlation_id:b.correlation_id,idempotency_key:'n8n:'+b.idempotency_key,workflow_key:b.workflow_key,execution_id:String($execution.id),status:'COMPLETED',actions:(b.executed_actions||[]).map(item=>({type:item.type})),completed_at:new Date().toISOString(),tenant_id:b.tenant_id}}];"""


def middleware_request(node_id: str, name: str, path: str, body: str, position: list[int]) -> dict:
    return {
        "id": node_id, "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
        "position": position, "parameters": {
            "method": "POST", "url": "=http://codestra-integration-control-plane-api-1:8096" + path,
            "authentication": "predefinedCredentialType", "nodeCredentialType": "oAuth2Api",
            "sendHeaders": True, "headerParameters": {"parameters": [
                {"name": "X-Tenant-ID", "value": "={{$json.tenant_id}}"},
                {"name": "Idempotency-Key", "value": "={{$json.idempotency_key}}"},
                {"name": "X-Correlation-ID", "value": "={{$json.correlation_id}}"},
            ]}, "sendBody": True, "contentType": "raw", "rawContentType": "application/json",
            "body": body, "options": {"timeout": 10000, "response": {"response": {"neverError": False}}},
        },
        "credentials": {"oAuth2Api": {"id": "codestraMiddlewareOAuth2", "name": "Codestra Middleware OAuth2"}},
    }


def event_workflow(index: int, name: str, event_type: str) -> dict:
    slug = name.replace(".", "-")
    webhook = {"id": f"cp-{index:02d}-webhook", "name": "Authenticated middleware event", "type": "n8n-nodes-base.webhook", "typeVersion": 2,
               "position": [0, 0], "webhookId": f"codestra-{slug}",
               "parameters": {"httpMethod": "POST", "path": f"codestra-{slug}", "authentication": "headerAuth", "responseMode": "lastNode"},
               "credentials": {"httpHeaderAuth": {"id": "codestraMiddlewareHeaderAuth", "name": "Codestra Middleware Header Auth"}}}
    validate = {"id": f"cp-{index:02d}-validate", "name": "Validate and preserve context", "type": "n8n-nodes-base.code", "typeVersion": 2,
                "position": [260, 0], "parameters": {"jsCode": validation_code(name, event_type)}}
    authorize = middleware_request(f"cp-{index:02d}-authorize", "Authorize in Middleware", "/api/v1/automation/authorize", "={{JSON.stringify($json)}}", [520, 0])
    execute = middleware_request(f"cp-{index:02d}-execute", "Execute governed business process", "/api/v1/automation/execute", "={{JSON.stringify($json)}}", [780, 0])
    result = {"id": f"cp-{index:02d}-result", "name": "Build governed completion", "type": "n8n-nodes-base.code", "typeVersion": 2,
              "position": [1040, 0], "parameters": {"jsCode": result_code()}}
    callback = middleware_request(f"cp-{index:02d}-callback", "Record execution result", "/api/v1/automation/results", "={{JSON.stringify($json)}}", [1300, 0])
    names = [node["name"] for node in (webhook, validate, authorize, execute, result, callback)]
    return {
        "id": f"CodestraCP{index:02d}", "name": f"CP-{index:02d}-{name.upper()}-V1", "active": False,
        "nodes": [webhook, validate, authorize, execute, result, callback],
        "connections": {names[i]: {"main": [[{"node": names[i + 1], "type": "main", "index": 0}]]} for i in range(5)},
        "settings": {"executionOrder": "v1", "errorWorkflow": "CodestraCP90", "saveExecutionProgress": True,
                     "saveManualExecutions": False, "timezone": "America/Santo_Domingo"},
        "tags": [], "meta": {"templateCredsSetupCompleted": False},
    }


def error_workflow() -> dict:
    return {
        "id": "CodestraCP90", "name": "CP-90-STANDARD-ERROR-V1", "active": False,
        "nodes": [
            {"id": "cp-90-trigger", "name": "Workflow Error", "type": "n8n-nodes-base.errorTrigger", "typeVersion": 1, "position": [0, 0], "parameters": {}},
            {"id": "cp-90-structure", "name": "Structure failure", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [280, 0],
             "parameters": {"jsCode": "const e=$json.execution||{}; const executionId=String(e.id||$execution.id); return [{json:{ok:false,status:'FAILED',workflow_key:'resolve-from-execution',execution_id:executionId,event_id:'resolve-from-execution',correlation_id:'resolve-from-execution',idempotency_key:'n8n-failure:'+executionId,tenant_id:String($json.tenant_id||'unknown'),actions:[],completed_at:new Date().toISOString(),error:{name:e.error?.name||'WorkflowError',message:e.error?.message||'workflow_failed'}}}];"}},
            middleware_request("cp-90-callback", "Record governed failure", "/api/v1/automation/results", "={{JSON.stringify($json)}}", [560, 0]),
        ],
        "connections": {
            "Workflow Error": {"main": [[{"node": "Structure failure", "type": "main", "index": 0}]]},
            "Structure failure": {"main": [[{"node": "Record governed failure", "type": "main", "index": 0}]]},
        },
        "settings": {"executionOrder": "v1", "saveExecutionProgress": True, "saveManualExecutions": False,
                     "timezone": "America/Santo_Domingo"}, "tags": [], "meta": {"templateCredsSetupCompleted": False},
    }


def main() -> None:
    json.dump([error_workflow(), *[event_workflow(*spec) for spec in SPECS]], sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
