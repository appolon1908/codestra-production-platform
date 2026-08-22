#!/usr/bin/env python3
"""Build deterministic governed n8n imports without embedding credentials."""
from __future__ import annotations

import json
import sys

SPECS = [
    (17, "sms.submitted", "telnexa.sms.submitted"),
    (18, "sms.sent", "telnexa.sms.sent"),
    (19, "sms.rejected", "telnexa.sms.rejected"),
    (20, "sms.received", "telnexa.sms.received"),
    (21, "sms.delivered", "telnexa.sms.delivered"),
    (22, "sms.failed", "telnexa.sms.failed"),
    (23, "sms.opted_out", "telnexa.sms.opted_out"),
    (24, "email.delivered", "klyrow.email.delivered"),
    (25, "email.bounced", "klyrow.email.bounced"),
    (26, "email.complained", "klyrow.email.complained"),
    (27, "email.unsubscribed", "klyrow.email.unsubscribed"),
    (28, "crawler.result.created", "kyqra.record.created"),
    (29, "crawler.job.completed", "kyqra.job.completed"),
    (30, "crawler.job.failed", "kyqra.job.failed"),
    (31, "customer.created", "customer.created"),
    (32, "customer.updated", "customer.updated"),
    (33, "email.deferred", "klyrow.email.deferred"),
    (34, "crm.lead.created", "crm.lead.created"),
    (35, "crm.lead.updated", "crm.lead.updated"),
    (36, "crm.activity.created", "crm.activity.created"),
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
const correlationId=String(b.correlation_id);
const tenantId=String(b.tenant_id);
const customerId=b.customer_id==null?null:String(b.customer_id);
return [{json:{accepted:true,duplicate:false,event_id:eventId,event_type:b.event_type,correlation_id:correlationId,tenant_id:tenantId,customer_id:customerId,idempotency_key:String(b.idempotency_key),payload:b.payload||{},structured_error:null,structured_log:{level:'info',workflow:WORKFLOW,event_id:eventId,correlation_id:correlationId,tenant_id:tenantId,customer_id:customerId}}}];
""".replace("EVENT_TYPE", json.dumps(event_type)).replace("WORKFLOW", json.dumps(name))


def event_workflow(index: int, name: str, event_type: str) -> dict:
    slug = name.replace(".", "-")
    return {
        "id": f"CodestraCP{index:02d}", "name": f"CP-{index:02d}-{name.upper()}-V1", "active": False,
        "nodes": [
            {"id": f"cp-{index:02d}-webhook", "name": "Authenticated middleware event", "type": "n8n-nodes-base.webhook", "typeVersion": 2,
             "position": [0, 0], "webhookId": f"codestra-{slug}",
             "parameters": {"httpMethod": "POST", "path": f"codestra-{slug}", "authentication": "headerAuth", "responseMode": "lastNode"},
             "credentials": {"httpHeaderAuth": {"id": "codestraMiddlewareHeaderAuth", "name": "Codestra Middleware Header Auth"}}},
            {"id": f"cp-{index:02d}-validate", "name": "Validate, deduplicate and preserve context", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [280, 0],
             "parameters": {"jsCode": validation_code(name, event_type)}},
        ],
        "connections": {"Authenticated middleware event": {"main": [[{"node": "Validate, deduplicate and preserve context", "type": "main", "index": 0}]]}},
        "settings": {"executionOrder": "v1", "errorWorkflow": "CodestraCP90", "saveExecutionProgress": True, "saveManualExecutions": True, "timezone": "America/Santo_Domingo"},
        "tags": [], "meta": {"templateCredsSetupCompleted": False},
    }


def error_workflow() -> dict:
    return {
        "id": "CodestraCP90", "name": "CP-90-STANDARD-ERROR-V1", "active": False,
        "nodes": [
            {"id": "cp-90-trigger", "name": "Workflow Error", "type": "n8n-nodes-base.errorTrigger", "typeVersion": 1, "position": [0, 0], "parameters": {}},
            {"id": "cp-90-structure", "name": "Structure failure", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [280, 0],
             "parameters": {"jsCode": "const e=$json.execution||{}; const w=$json.workflow||{}; return [{json:{ok:false,failure_path:'common_error_workflow',workflow_id:w.id||null,workflow_name:w.name||null,execution_id:e.id||null,correlation_id:$json.correlation_id||null,tenant_id:$json.tenant_id||null,customer_id:$json.customer_id||null,error:{name:e.error?.name||'WorkflowError',message:e.error?.message||'workflow_failed'},occurred_at:new Date().toISOString()}}];"}},
        ],
        "connections": {"Workflow Error": {"main": [[{"node": "Structure failure", "type": "main", "index": 0}]]}},
        "settings": {"executionOrder": "v1", "saveExecutionProgress": True, "saveManualExecutions": True, "timezone": "America/Santo_Domingo"},
        "tags": [], "meta": {"templateCredsSetupCompleted": False},
    }


def main() -> None:
    json.dump([error_workflow(), *[event_workflow(*spec) for spec in SPECS]], sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
