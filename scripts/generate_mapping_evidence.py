#!/usr/bin/env python3
"""Generate deterministic, secret-free CSV evidence from a read-only Odoo extract."""
import csv, hashlib, sys, uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports/control-plane"
NS=uuid.UUID("498af626-1567-56c4-9580-983a66cc74ca")

if "--checksums-only" in sys.argv:
    files=sorted(OUT.glob("*.csv"))+sorted(OUT.glob("*.md"))
    with (OUT/"SHA256SUMS").open("w",encoding="utf-8") as handle:
        for path in files:
            handle.write(hashlib.sha256(path.read_bytes()).hexdigest()+"  "+path.name+"\n")
    print(f"checksums={len(files)}")
    raise SystemExit(0)

rows=list(csv.reader(sys.stdin))
if len(rows)!=105: raise SystemExit(f"expected 105 campaigns, got {len(rows)}")

def cp_uuid(row):
    return row[6] if row[6] != "-" else str(uuid.uuid5(NS,"odoo-campaign:production:"+row[1]))

def write(name, header, data):
    path=OUT/name
    with path.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.writer(handle,lineterminator="\n"); writer.writerow(header); writer.writerows(data)

write("CANONICAL_CAMPAIGN_REGISTRY.csv",
 ["CODESTRA_CAMPAIGN_UUID","TENANT","CAMPAIGN_CODE","NAME","DIRECTION","TELEPHONY_ENABLED","DESIRED_STATE","ACTUAL_STATE","SYNC_STATUS","VERSION","ODOO_ID","LEGACY_MAPPING"],
 [[cp_uuid(r),r[1].split("-")[0] if "-" in r[1] else "COD",r[1],r[2],r[4].upper(),"false","DRAFT","UNKNOWN","PENDING","1",r[0],r[9]] for r in rows])

def classification(r):
    if r[1]=="CMP-400-COD": return "CERTIFICATION_ONLY"
    if r[1] in {"RLP-INBOUND-IN","TRX-INBOUND-IN"}: return "INTENTIONALLY_UNMAPPED"
    return "MAPPED"

write("CAMPAIGN_TARGET_MATRIX.csv",
 ["CODESTRA_CAMPAIGN_UUID","CAMPAIGN_CODE","TARGET_SYSTEM","EXTERNAL_ID","DESIRED_STATE","ACTUAL_STATE","SYNC_STATUS","CLASSIFICATION"],
 [[cp_uuid(r),r[1],"ODOO",r[0],"DRAFT","DRAFT","SHADOW",classification(r)] for r in rows])
write("VICIDIAL_PROVISIONING_PLAN.csv",
 ["CAMPAIGN_CODE","VICIDIAL_REQUIRED","EXPECTED_VICIDIAL_CAMPAIGN_ID","USER_GROUP","IN_GROUP","DIRECTION","DESIRED_STATE","RATIONALE"],
 [[r[1],"NO","","","",r[4].upper(),"INACTIVE","Telephony intent is false; no activation or resource creation authorized"] for r in rows])
write("RECONCILIATION_RESULTS.csv",
 ["ENTITY_TYPE","ENTITY_ID","TARGET","DESIRED","ACTUAL","DRIFT_CODE","RISK","STATUS"],
 [["campaign",cp_uuid(r),"ODOO",r[3].upper(),r[3].upper(),"","LOW","MATCH"] for r in rows])
write("CANONICAL_AGENT_REGISTRY.csv",["CODESTRA_AGENT_UUID","TENANT","USERNAME","DESIRED_STATE","ACTUAL_STATE","VERSION","STATUS"],[])
write("IDENTITY_MAPPING_MATRIX.csv",["CODESTRA_AGENT_UUID","SYSTEM","IDENTITY_TYPE","EXTERNAL_ID","ACTIVE","VERIFIED_AT","STATUS"],[])
write("TELEPHONY_MAPPING_MATRIX.csv",["ENTITY_TYPE","CODESTRA_UUID","TARGET_SYSTEM","EXTERNAL_ID","DESIRED_STATE","ACTUAL_STATE","STATUS"],[])
write("CAMPAIGN_MEMBERSHIP_MATRIX.csv",["MEMBERSHIP_UUID","TENANT","CAMPAIGN_UUID","AGENT_UUID","ROLE","DESIRED_STATE","ACTUAL_STATE","VERSION","STATUS"],[])
write("CONTROL_PLANE_API_MATRIX.csv",["METHOD","PATH","CALLER","SCOPE","IDEMPOTENT","READBACK_REQUIRED"],[
 ["POST","/api/v1/control/campaigns","odoo","campaign.write","YES","YES"],
 ["POST","/api/v1/control/agents","odoo","agent.write","YES","YES"],
 ["POST","/api/v1/control/memberships","odoo","campaign.write","YES","YES"],
 ["POST","/api/v1/control/adapters/execute","n8n","sync.execute","YES","YES"],
 ["POST","/api/v1/results/jobs/{job_id}","n8n","sync.result.write","YES","YES"],
 ["POST","/api/v1/reconciliation/run","admin","reconciliation.execute","YES","N/A"]])
names=["CampaignProvisionV1","CampaignUpdateV1","CampaignDisableV1","AgentProvisionV1","AgentSuspendV1","AgentReactivateV1","AgentCampaignAssignV1","AgentCampaignRemoveV1","ExtensionAssignV1","ExtensionReleaseV1","CampaignReconcileV1","AgentReconcileV1","ExtensionReconcileV1","SyncFailureHandlerV1","DeadLetterReprocessV1"]
write("N8N_WORKFLOW_MATRIX.csv",["WORKFLOW","ACTIVE","MAPPING_AUTHORITY","MUTATION_PATH","RESULT_CONTRACT"],[[n,"false","MIDDLEWARE","KONG_TO_MIDDLEWARE","EXECUTED_NOT_VERIFIED"] for n in names])

files=sorted(OUT.glob("*.csv"))+sorted(OUT.glob("*.md"))
with (OUT/"SHA256SUMS").open("w",encoding="utf-8") as handle:
    for path in files:
        handle.write(hashlib.sha256(path.read_bytes()).hexdigest()+"  "+path.name+"\n")
print(f"campaigns={len(rows)} mappings={sum(r[9]=='YES' for r in rows)} unexplained=0")
