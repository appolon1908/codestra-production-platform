#!/usr/bin/env python3
"""Generate the production candidate CRM workflow catalog, inactive by default."""
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
OUT = ROOT / "workflows" / "campaign_crm"

CORE = [
    "CDST_EventRouter_v2", "CDST_CampaignRouter_v2", "CDST_LeadAssignment_v1",
    "CDST_NextActionCreated_v1", "CDST_FollowupDue_v1", "CDST_FollowupOverdue_v1",
    "CDST_AppointmentCreated_v1", "CDST_Appointment24HourReminder_v1",
    "CDST_Appointment1HourReminder_v1", "CDST_CustomerNoShow_v1", "CDST_AgentNoShow_v1",
    "CDST_CallbackDue_v1", "CDST_CallbackOverdue_v1", "CDST_NoActivity_v1",
    "CDST_SupervisorEscalation_v1", "CDST_ManagerEscalation_v1", "CDST_EmailSend_v1",
    "CDST_SMSAuthorizedSend_v1", "CDST_EmailReplyReceived_v1", "CDST_SMSReplyReceived_v1",
    "CDST_DocumentRequested_v1", "CDST_DocumentMissing_v1", "CDST_DocumentReceived_v1",
    "CDST_AIWorkRequested_v1", "CDST_AIWorkCompleted_v1", "CDST_AIHumanHandoff_v1",
    "CDST_DailyAgentReport_v1", "CDST_DailySupervisorReport_v1", "CDST_DailyCampaignReport_v1",
    "CDST_DailyAdminReport_v1", "CDST_ErrorHandler_v1", "CDST_DeadLetterRecovery_v1",
    "CDST_CompleteExecution_v2",
]
CAMPAIGN = {
    "transportation": ["quote_requested", "quote_sent_followup", "carrier_packet", "load_booked", "pickup_reminder", "delivery_followup", "repeat_load"],
    "codestra": ["discovery_scheduled", "discovery_completed", "technical_review", "proposal_sent", "proposal_overdue", "contract_sent", "deposit_received", "project_handoff", "retainer_followup"],
    "moneybee": ["prequalified", "documents_requested", "documents_partial", "documents_overdue", "application_started", "underwriting_followup", "additional_info", "offer_sent", "funding_followup", "post_funding", "renewal"],
    "senior": ["product_selected", "payment_pending", "payment_confirmed", "shipped", "delivery_followup", "support", "reorder_due"],
    "student": ["eligibility_review", "documents_requested", "documents_missing", "counselor_appointment", "submission", "response_followup", "additional_info", "enrollment_followup"],
}


NODE_VERSIONS = {
    "n8n-nodes-base.webhook": 2.1,
    "n8n-nodes-base.code": 2,
    "n8n-nodes-base.httpRequest": 4.2,
    "n8n-nodes-base.respondToWebhook": 1.4,
}


def node(node_id, name, type_name, position, parameters):
    return {
        "id": node_id,
        "name": name,
        "type": type_name,
        "typeVersion": NODE_VERSIONS[type_name],
        "position": position,
        "parameters": parameters,
    }


KONG_BASE_URL = "https://api.codestra.co"
KONG_OAUTH_CREDENTIAL = {
    "id": "codestraN8nCommunicationsOAuth",
    "name": "Codestra n8n Communications OAuth",
}


def middleware_request(node_id, name, position, path):
    value = node(node_id, name, "n8n-nodes-base.httpRequest", position, {
        "authentication": "genericCredentialType",
        "genericAuthType": "oAuth2Api",
        "method": "POST",
        "url": f"{KONG_BASE_URL}{path}",
        "sendBody": True,
        "contentType": "raw",
        "rawContentType": "application/json",
        "body": "={{JSON.stringify($json)}}",
        "options": {"timeout": 10000},
    })
    value["credentials"] = {
        "oAuth2Api": KONG_OAUTH_CREDENTIAL,
    }
    return value


def workflow(name):
    validation = """const e=$json.body||$json; const required=['schema_version','event_id','event_type','correlation_id','idempotency_key','tenant_id','business_unit_id','campaign_id','entity_type','entity_id','actor_type','actor_id','occurred_at','automation_key','payload']; for (const k of required) if (e[k]===undefined||e[k]===null||e[k]==='') throw new Error('missing '+k); if(e.schema_version!=='1') throw new Error('unsupported schema'); if(!['HUMAN','AI','SYSTEM'].includes(e.actor_type)) throw new Error('invalid actor'); return [{json:e}];"""
    result = """const e=$json; return [{json:{event_id:e.event_id,correlation_id:e.correlation_id,idempotency_key:e.idempotency_key,workflow_key:e.automation_key,execution_id:$execution.id,status:'COMPLETED',actions:[],completed_at:new Date().toISOString()}}];"""
    nodes = [
        node("trigger", "Receive Standard Event", "n8n-nodes-base.webhook", [0, 0], {"httpMethod": "POST", "path": f"crm/{name.lower()}", "responseMode": "responseNode"}),
        node("validate", "Validate Trusted Envelope", "n8n-nodes-base.code", [240, 0], {"jsCode": validation}),
        middleware_request("policy", "Middleware Authorization", [480, 0], "/api/v1/automation/policy-check"),
        node("result", "Build Standard Result", "n8n-nodes-base.code", [720, 0], {"jsCode": result}),
        middleware_request("complete", "Return Result Through Middleware", [960, 0], "/api/v1/integrations/n8n/results"),
        node("response", "Acknowledge", "n8n-nodes-base.respondToWebhook", [1200, 0], {"respondWith": "json", "responseBody": "={{JSON.stringify({accepted:true,event_id:$json.event_id})}}", "options": {"responseCode": 202}}),
    ]
    connections = {nodes[i]["name"]: {"main": [[{"node": nodes[i + 1]["name"], "type": "main", "index": 0}]]} for i in range(len(nodes) - 1)}
    return {"id": name, "name": name, "active": False, "nodes": nodes, "connections": connections,
            "settings": {"executionOrder": "v1", "timezone": "America/Santo_Domingo"},
            "meta": {"schema_version": "1", "middleware_only": True, "kong_only": True,
                     "oauth_client": "codestra-n8n-communications", "direct_database_access": False,
                     "credentials_embedded": False, "production_activation_requires_gate": True}}


names = CORE + [f"{prefix}_{suffix}" for prefix, suffixes in CAMPAIGN.items() for suffix in suffixes]
OUT.mkdir(parents=True, exist_ok=True)
for name in names:
    (OUT / f"{name}.json").write_text(json.dumps(workflow(name), indent=2) + "\n")
(ROOT / "manifests" / "campaign-crm-workflow-manifest.json").write_text(json.dumps({
    "schema_version": "1", "workflow_count": len(names), "active": False,
    "workflows": [{"id": name, "path": f"workflows/campaign_crm/{name}.json"} for name in names],
}, indent=2) + "\n")
print(f"generated {len(names)} inactive campaign CRM workflows")
