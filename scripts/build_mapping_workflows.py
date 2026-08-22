#!/usr/bin/env python3
"""Build inactive, stateless mapping orchestration workflows."""
import json
import sys

NAMES = [
 "CampaignProvisionV1","CampaignUpdateV1","CampaignDisableV1",
 "AgentProvisionV1","AgentSuspendV1","AgentReactivateV1",
 "AgentCampaignAssignV1","AgentCampaignRemoveV1",
 "ExtensionAssignV1","ExtensionReleaseV1","CampaignReconcileV1",
 "AgentReconcileV1","ExtensionReconcileV1","SyncFailureHandlerV1",
 "DeadLetterReprocessV1",
]

def workflow(index, name):
    validate = """const b=$json.body||$json;
for(const k of ['schema_version','event_id','correlation_id','idempotency_key','tenant','event_kind','event_type','entity_type','entity_id','entity_version','occurred_at','payload']) if(b[k]===undefined||b[k]===null||b[k]==='') throw new Error(k+'_required');
if(b.schema_version!=='1') throw new Error('schema_version_rejected');
if(b.event_kind!=='COMMAND') throw new Error('command_required');
if(!Number.isInteger(b.entity_version)||b.entity_version<1) throw new Error('entity_version_invalid');
return [{json:b}];"""
    result = """const b=$json; return [{json:{schema_version:'1',event_kind:'RESULT',event_type:b.event_type.replace(/requested$/, 'result'),event_id:$execution.id+'-'+b.event_id,correlation_id:b.correlation_id,idempotency_key:b.idempotency_key,tenant:b.tenant,entity_type:b.entity_type,entity_id:b.entity_id,entity_version:b.entity_version,occurred_at:new Date().toISOString(),payload:{workflow_execution_id:$execution.id,status:'EXECUTED_NOT_VERIFIED'}}}];"""
    return {"id":f"CodestraMap{index:02d}","name":name,"active":False,"nodes":[
      {"id":f"map-{index}-hook","name":"Middleware command","type":"n8n-nodes-base.webhook","typeVersion":2,"position":[0,0],"parameters":{"httpMethod":"POST","path":"control-"+name.lower(),"authentication":"headerAuth","responseMode":"lastNode"},"credentials":{"httpHeaderAuth":{"id":"codestraMiddlewareMappingHeaderAuth","name":"Codestra Middleware Mapping Header Auth"}}},
      {"id":f"map-{index}-validate","name":"Validate envelope and version","type":"n8n-nodes-base.code","typeVersion":2,"position":[260,0],"parameters":{"jsCode":validate}},
      {"id":f"map-{index}-execute","name":"Execute via Kong middleware adapter","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[520,0],"parameters":{"method":"POST","url":"={{$env.CODESTRA_KONG_CONTROL_URL + '/api/v1/control/adapters/execute'}}","sendHeaders":True,"headerParameters":{"parameters":[{"name":"X-Correlation-ID","value":"={{$json.correlation_id}}"},{"name":"Idempotency-Key","value":"={{$json.idempotency_key}}"}]},"sendBody":True,"contentType":"raw","rawContentType":"application/json","body":"={{JSON.stringify($json)}}","options":{"timeout":30000}},"credentials":{"httpHeaderAuth":{"id":"codestraN8nControlToken","name":"Codestra n8n Control Token"}}},
      {"id":f"map-{index}-result","name":"Explicit unverified result","type":"n8n-nodes-base.code","typeVersion":2,"position":[780,0],"parameters":{"jsCode":result}},
      {"id":f"map-{index}-callback","name":"Return result through Kong","type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":[1040,0],"parameters":{"method":"POST","url":"={{$env.CODESTRA_KONG_CONTROL_URL + '/api/v1/results/jobs/' + $json.payload.job_id}}","sendHeaders":True,"headerParameters":{"parameters":[{"name":"X-Correlation-ID","value":"={{$json.correlation_id}}"},{"name":"Idempotency-Key","value":"={{$json.idempotency_key}}"}]},"sendBody":True,"contentType":"raw","rawContentType":"application/json","body":"={{JSON.stringify($json)}}","options":{"timeout":30000}},"credentials":{"httpHeaderAuth":{"id":"codestraN8nResultToken","name":"Codestra n8n Result Token"}}}],
      "connections":{"Middleware command":{"main":[[{"node":"Validate envelope and version","type":"main","index":0}]]},"Validate envelope and version":{"main":[[{"node":"Execute via Kong middleware adapter","type":"main","index":0}]]},"Execute via Kong middleware adapter":{"main":[[{"node":"Explicit unverified result","type":"main","index":0}]]},"Explicit unverified result":{"main":[[{"node":"Return result through Kong","type":"main","index":0}]]}},
      "settings":{"executionOrder":"v1","saveExecutionProgress":True,"timezone":"America/Santo_Domingo"},"tags":[]}

json.dump([workflow(i+1,n) for i,n in enumerate(NAMES)],sys.stdout,indent=2)
print()
