"""Canonical cross-system mapping registry and reconciliation control plane.

The registry is deliberately independent from n8n and destination adapters.  A
transaction records desired state, a job, and an outbox event.  Workers may
execute the job, but only a destination read-back can move it to SYNCED.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .core import ControlPlaneError
from .database import Connection, IntegrityError, is_postgres


ENTITY_STATES = {"DRAFT", "READY", "ACTIVE", "INACTIVE", "SUSPENDED", "ARCHIVED"}
SYNC_STATES = {
    "DRAFT", "VALIDATED", "READY", "SYNC_REQUESTED", "SYNCING", "VERIFYING",
    "SYNCED", "FAILED", "RETRY_PENDING", "DEAD_LETTER", "DRIFTED",
    "RECONCILING",
}
TRANSITIONS = {
    "DRAFT": {"VALIDATED"}, "VALIDATED": {"READY"},
    "READY": {"SYNC_REQUESTED"}, "SYNC_REQUESTED": {"SYNCING"},
    "SYNCING": {"VERIFYING", "FAILED"},
    "VERIFYING": {"SYNCED", "DRIFTED", "FAILED"},
    "SYNCED": {"DRIFTED", "SYNC_REQUESTED"},
    "FAILED": {"RETRY_PENDING", "DEAD_LETTER"},
    "RETRY_PENDING": {"SYNCING", "DEAD_LETTER"},
    "DRIFTED": {"RECONCILING"}, "RECONCILING": {"VERIFYING", "FAILED"},
    "DEAD_LETTER": {"RETRY_PENDING"},
}
DRIFT_CODES = {
    "CAMPAIGN_MISSING", "CAMPAIGN_STATE_MISMATCH", "USER_MISSING",
    "USER_STATE_MISMATCH", "USER_GROUP_MISMATCH", "MEMBERSHIP_MISSING",
    "MEMBERSHIP_EXTRA", "EXTENSION_MISMATCH", "IDENTITY_MISMATCH",
    "STALE_VERSION", "UNKNOWN_EXTERNAL_RESOURCE",
}
TARGETS = {"ODOO", "VICIDIAL", "N8N", "PROVISIONING", "OTHER_APPROVED_TARGET"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def new_uuid() -> str:
    return str(uuid.uuid4())


def db_bool(value: bool) -> bool | int:
    return value if is_postgres() else int(value)


SCHEMA = """
CREATE TABLE IF NOT EXISTS cp_campaign(
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,campaign_code TEXT NOT NULL,name TEXT NOT NULL,
 direction TEXT NOT NULL,telephony_enabled INTEGER NOT NULL DEFAULT 0,
 desired_state TEXT NOT NULL,effective_state TEXT,version INTEGER NOT NULL DEFAULT 1,
 sync_status TEXT NOT NULL DEFAULT 'DRAFT',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 last_reconciled_at TEXT,UNIQUE(tenant_id,campaign_code));
CREATE TABLE IF NOT EXISTS cp_campaign_target(
 id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,target_system TEXT NOT NULL,external_id TEXT,
 desired_state TEXT NOT NULL,actual_state TEXT,last_synced_version INTEGER,last_synced_at TEXT,
 sync_status TEXT NOT NULL DEFAULT 'DRAFT',error_code TEXT,error_detail_safe TEXT,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(campaign_id,target_system),
 FOREIGN KEY(campaign_id) REFERENCES cp_campaign(id));
CREATE TABLE IF NOT EXISTS cp_agent(
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,username TEXT NOT NULL,business_state TEXT NOT NULL,
 desired_state TEXT NOT NULL,actual_state TEXT,version INTEGER NOT NULL DEFAULT 1,
 sync_status TEXT NOT NULL DEFAULT 'DRAFT',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(tenant_id,username));
CREATE TABLE IF NOT EXISTS cp_agent_identity(
 id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,system TEXT NOT NULL,identity_type TEXT NOT NULL,
 external_id TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,verified_at TEXT,
 version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(system,identity_type,external_id),UNIQUE(agent_id,system,identity_type),
 FOREIGN KEY(agent_id) REFERENCES cp_agent(id));
CREATE TABLE IF NOT EXISTS cp_extension(
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,extension_number TEXT NOT NULL,
 asterisk_endpoint TEXT,vicidial_phone TEXT,desired_state TEXT NOT NULL,actual_state TEXT,
 version INTEGER NOT NULL DEFAULT 1,sync_status TEXT NOT NULL DEFAULT 'DRAFT',
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tenant_id,extension_number));
CREATE TABLE IF NOT EXISTS cp_extension_assignment(
 id TEXT PRIMARY KEY,extension_id TEXT NOT NULL,agent_id TEXT NOT NULL,desired_state TEXT NOT NULL,
 actual_state TEXT,version INTEGER NOT NULL DEFAULT 1,effective_from TEXT NOT NULL,effective_until TEXT,
 last_reconciled_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 FOREIGN KEY(extension_id) REFERENCES cp_extension(id),FOREIGN KEY(agent_id) REFERENCES cp_agent(id));
CREATE UNIQUE INDEX IF NOT EXISTS cp_one_active_extension_owner
 ON cp_extension_assignment(extension_id) WHERE effective_until IS NULL AND desired_state='ACTIVE';
CREATE TABLE IF NOT EXISTS cp_membership(
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,campaign_id TEXT NOT NULL,agent_id TEXT NOT NULL,
 desired_state TEXT NOT NULL,actual_state TEXT,role TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,
 sync_status TEXT NOT NULL DEFAULT 'DRAFT',effective_from TEXT NOT NULL,effective_until TEXT,
 last_reconciled_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 FOREIGN KEY(campaign_id) REFERENCES cp_campaign(id),FOREIGN KEY(agent_id) REFERENCES cp_agent(id));
CREATE UNIQUE INDEX IF NOT EXISTS cp_one_active_membership
 ON cp_membership(campaign_id,agent_id,role) WHERE effective_until IS NULL AND desired_state='ACTIVE';
CREATE TABLE IF NOT EXISTS cp_idempotency(
 tenant_id TEXT NOT NULL,operation TEXT NOT NULL,idempotency_key TEXT NOT NULL,
 request_hash TEXT NOT NULL,response_json TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,operation,idempotency_key));
CREATE TABLE IF NOT EXISTS cp_sync_job(
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,
 entity_version INTEGER NOT NULL,operation TEXT NOT NULL,status TEXT NOT NULL,correlation_id TEXT NOT NULL,
 idempotency_key TEXT NOT NULL,attempt_count INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 5,
 error_code TEXT,error_detail_safe TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(tenant_id,operation,idempotency_key));
CREATE TABLE IF NOT EXISTS cp_sync_step(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL,step_name TEXT NOT NULL,status TEXT NOT NULL,
 attempt INTEGER NOT NULL DEFAULT 0,started_at TEXT,completed_at TEXT,error_code TEXT,
 error_detail_safe TEXT,UNIQUE(job_id,step_name),FOREIGN KEY(job_id) REFERENCES cp_sync_job(id));
CREATE TABLE IF NOT EXISTS cp_sync_result(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL,entity_version INTEGER NOT NULL,result_type TEXT NOT NULL,
 payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,verified INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,UNIQUE(job_id,payload_hash),FOREIGN KEY(job_id) REFERENCES cp_sync_job(id));
CREATE TABLE IF NOT EXISTS cp_event(
 id TEXT PRIMARY KEY,schema_version TEXT NOT NULL,correlation_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,
 tenant_id TEXT NOT NULL,event_kind TEXT NOT NULL,event_type TEXT NOT NULL,entity_type TEXT NOT NULL,
 entity_id TEXT NOT NULL,entity_version INTEGER NOT NULL,payload_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL,occurred_at TEXT NOT NULL,published_at TEXT,
 UNIQUE(tenant_id,event_type,idempotency_key));
CREATE TABLE IF NOT EXISTS cp_event_delivery(
 id TEXT PRIMARY KEY,event_id TEXT NOT NULL,target TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING',
 attempt_count INTEGER NOT NULL DEFAULT 0,next_attempt_at TEXT,last_error_code TEXT,
 last_error_safe TEXT,delivered_at TEXT,UNIQUE(event_id,target),FOREIGN KEY(event_id) REFERENCES cp_event(id));
CREATE TABLE IF NOT EXISTS cp_reconciliation_run(
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,scope TEXT NOT NULL,status TEXT NOT NULL,
 correlation_id TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,difference_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS cp_reconciliation_difference(
 id TEXT PRIMARY KEY,run_id TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,
 target_system TEXT NOT NULL,drift_code TEXT NOT NULL,risk TEXT NOT NULL,desired_json TEXT NOT NULL,
 actual_json TEXT NOT NULL,remediation_status TEXT NOT NULL DEFAULT 'OPEN',created_at TEXT NOT NULL,
 FOREIGN KEY(run_id) REFERENCES cp_reconciliation_run(id));
CREATE TABLE IF NOT EXISTS cp_dead_letter(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,
 entity_version INTEGER NOT NULL,error_code TEXT NOT NULL,error_detail_safe TEXT,
 attempt_count INTEGER NOT NULL,first_failure_at TEXT NOT NULL,last_failure_at TEXT NOT NULL,
 created_at TEXT NOT NULL,UNIQUE(job_id),FOREIGN KEY(job_id) REFERENCES cp_sync_job(id));
CREATE TABLE IF NOT EXISTS cp_audit(
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,actor_type TEXT NOT NULL,actor_id TEXT NOT NULL,
 action TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,entity_version INTEGER,
 correlation_id TEXT NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL);
"""


class MappingRegistry:
    def __init__(self, path: str):
        self.path = path
        with Connection(path) as db:
            if is_postgres():
                db.execute("CREATE SCHEMA IF NOT EXISTS control_plane")
            db.executescript(SCHEMA)

    def _audit(self, db: Connection, tenant: str, actor: str, action: str,
               entity_type: str, entity_id: str, version: int | None,
               correlation: str, metadata: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO cp_audit VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            new_uuid(), tenant, "MACHINE", actor, action, entity_type, entity_id,
            version, correlation, canonical(metadata or {}), now()))

    def create_campaign(self, value: dict[str, Any], *, actor: str) -> tuple[dict[str, Any], bool]:
        tenant = str(value["tenant_id"]); key = str(value["idempotency_key"])
        operation = "campaign.create"; digest = payload_hash(value.get("immutable_payload", value))
        stamp = now(); campaign_id = str(value.get("id") or new_uuid())
        desired = str(value.get("desired_state", "DRAFT")).upper()
        if desired not in ENTITY_STATES:
            raise ControlPlaneError("invalid_desired_state")
        correlation = str(value.get("correlation_id") or new_uuid())
        try:
            with Connection(self.path) as db:
                prior = db.execute("SELECT request_hash,response_json FROM cp_idempotency WHERE tenant_id=? AND operation=? AND idempotency_key=?", (tenant, operation, key)).fetchone()
                if prior:
                    if prior["request_hash"] != digest: raise ControlPlaneError("idempotency_conflict")
                    stored = prior["response_json"]
                    return (stored if isinstance(stored, dict) else json.loads(stored)), True
                db.execute("INSERT INTO cp_campaign VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    campaign_id, tenant, value["campaign_code"], value["name"],
                    str(value["direction"]).upper(), db_bool(bool(value.get("telephony_enabled", False))),
                    desired, None, 1, "DRAFT", stamp, stamp, None))
                response = self._request_sync_tx(db, tenant, "campaign", campaign_id, 1,
                    "campaign.provision.requested", key, correlation,
                    {"desired_state": desired, "campaign_code": value["campaign_code"]})
                db.execute("INSERT INTO cp_idempotency VALUES(?,?,?,?,?,?)", (tenant, operation, key, digest, canonical(response), stamp))
                self._audit(db, tenant, actor, "desired_state.created", "campaign", campaign_id, 1, correlation)
            return response, False
        except IntegrityError as exc:
            raise ControlPlaneError("mapping_collision") from exc

    def _request_sync_tx(self, db: Connection, tenant: str, entity_type: str,
                         entity_id: str, version: int, event_type: str,
                         key: str, correlation: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_id, event_id, stamp = new_uuid(), new_uuid(), now()
        envelope = {"schema_version":"1", "event_id":event_id,
            "correlation_id":correlation, "idempotency_key":key, "tenant":tenant,
            "event_kind":"COMMAND", "event_type":event_type, "entity_type":entity_type,
            "entity_id":entity_id, "entity_version":version, "occurred_at":stamp,
            "payload":payload}
        db.execute("INSERT INTO cp_sync_job VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            job_id,tenant,entity_type,entity_id,version,event_type,"SYNC_REQUESTED",
            correlation,key,0,5,None,None,stamp,stamp))
        db.execute("INSERT INTO cp_event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            event_id,"1",correlation,key,tenant,"COMMAND",event_type,entity_type,
            entity_id,version,canonical(payload),payload_hash(payload),stamp,None))
        db.execute("INSERT INTO cp_event_delivery VALUES(?,?,?,?,?,?,?,?,?)", (
            new_uuid(),event_id,"N8N","PENDING",0,None,None,None,None))
        return {"entity_id":entity_id,"entity_version":version,"job_id":job_id,
                "event":envelope,"sync_status":"SYNC_REQUESTED"}

    def transition_job(self, job_id: str, target: str, *, expected_version: int,
                       actor: str = "worker") -> dict[str, Any]:
        target = target.upper()
        with Connection(self.path) as db:
            row = db.execute("SELECT * FROM cp_sync_job WHERE id=?", (job_id,)).fetchone()
            if not row: raise ControlPlaneError("job_not_found")
            if int(row["entity_version"]) != expected_version: raise ControlPlaneError("stale_version")
            if target not in TRANSITIONS.get(row["status"], set()): raise ControlPlaneError("invalid_transition")
            db.execute("UPDATE cp_sync_job SET status=?,updated_at=? WHERE id=?", (target,now(),job_id))
            self._audit(db,row["tenant_id"],actor,"job.transitioned",row["entity_type"],row["entity_id"],expected_version,row["correlation_id"],{"from":row["status"],"to":target})
            result = dict(row); result["status"] = target
            return result

    def record_result(self, job_id: str, value: dict[str, Any], *, actor: str = "n8n") -> dict[str, Any]:
        with Connection(self.path) as db:
            job = db.execute("SELECT * FROM cp_sync_job WHERE id=?", (job_id,)).fetchone()
            if not job: raise ControlPlaneError("job_not_found")
            version = int(value["entity_version"])
            if version != int(job["entity_version"]): raise ControlPlaneError("stale_version")
            digest = payload_hash(value)
            prior = db.execute("SELECT * FROM cp_sync_result WHERE job_id=? AND payload_hash=?", (job_id,digest)).fetchone()
            if prior: return dict(prior)
            result_id = new_uuid()
            db.execute("INSERT INTO cp_sync_result VALUES(?,?,?,?,?,?,?,?)", (
                result_id,job_id,version,"RESULT",canonical(value),digest,db_bool(False),now()))
            self._audit(db,job["tenant_id"],actor,"workflow.result.received",job["entity_type"],job["entity_id"],version,job["correlation_id"])
            return {"id":result_id,"job_id":job_id,"verified":False,"sync_status":job["status"]}

    def verify(self, job_id: str, read_back: Callable[[dict[str, Any]], dict[str, Any]],
               desired: dict[str, Any]) -> dict[str, Any]:
        """Read destination state and mark SYNCED only after equality."""
        with Connection(self.path) as db:
            job = db.execute("SELECT * FROM cp_sync_job WHERE id=?", (job_id,)).fetchone()
            if not job: raise ControlPlaneError("job_not_found")
        actual = read_back(dict(job))
        status = "SYNCED" if actual == desired else "DRIFTED"
        with Connection(self.path) as db:
            db.execute("UPDATE cp_sync_job SET status=?,updated_at=? WHERE id=?", (status,now(),job_id))
            db.execute("UPDATE cp_sync_result SET verified=? WHERE job_id=?", (db_bool(status == "SYNCED"),job_id))
            self._audit(db,job["tenant_id"],"reconciler","destination.verified",job["entity_type"],job["entity_id"],job["entity_version"],job["correlation_id"],{"status":status,"desired_hash":payload_hash(desired),"actual_hash":payload_hash(actual)})
        return {"job_id":job_id,"desired":desired,"actual":actual,"sync_status":status,"verified":status == "SYNCED"}

    def reconcile(self, tenant: str, entity_type: str, entity_id: str,
                  target: str, desired: dict[str, Any], actual: dict[str, Any],
                  drift_code: str, *, correlation_id: str | None = None) -> dict[str, Any]:
        if drift_code not in DRIFT_CODES: raise ControlPlaneError("invalid_drift_code")
        if target not in TARGETS: raise ControlPlaneError("invalid_target")
        run_id, correlation, stamp = new_uuid(), correlation_id or new_uuid(), now()
        risk = "HIGH" if drift_code in {"IDENTITY_MISMATCH","EXTENSION_MISMATCH","UNKNOWN_EXTERNAL_RESOURCE"} else "LOW"
        different = desired != actual
        with Connection(self.path) as db:
            db.execute("INSERT INTO cp_reconciliation_run VALUES(?,?,?,?,?,?,?,?)", (run_id,tenant,entity_type,"COMPLETED",correlation,stamp,stamp,int(different)))
            if different:
                db.execute("INSERT INTO cp_reconciliation_difference VALUES(?,?,?,?,?,?,?,?,?,?,?)", (new_uuid(),run_id,entity_type,entity_id,target,drift_code,risk,canonical(desired),canonical(actual),"APPROVAL_REQUIRED" if risk == "HIGH" else "OPEN",stamp))
            self._audit(db,tenant,"reconciler","reconciliation.completed",entity_type,entity_id,None,correlation,{"different":different,"drift_code":drift_code})
        return {"run_id":run_id,"correlation_id":correlation,"difference_count":int(different),"risk":risk,"auto_remediation_allowed":different and risk == "LOW"}

    def fail_job(self, job_id: str, code: str, detail_safe: str, *, retryable: bool) -> str:
        with Connection(self.path) as db:
            job = db.execute("SELECT * FROM cp_sync_job WHERE id=?", (job_id,)).fetchone()
            if not job: raise ControlPlaneError("job_not_found")
            attempts = int(job["attempt_count"]) + 1
            status = "RETRY_PENDING" if retryable and attempts < int(job["max_attempts"]) else "DEAD_LETTER"
            db.execute("UPDATE cp_sync_job SET status=?,attempt_count=?,error_code=?,error_detail_safe=?,updated_at=? WHERE id=?", (status,attempts,code,detail_safe[:500],now(),job_id))
            if status == "DEAD_LETTER":
                stamp = now(); db.execute("INSERT INTO cp_dead_letter VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", (new_uuid(),job_id,job["entity_type"],job["entity_id"],job["entity_version"],code,detail_safe[:500],attempts,stamp,stamp,stamp))
            return status

    def get_job(self, job_id: str) -> dict[str, Any]:
        with Connection(self.path) as db:
            row = db.execute("SELECT * FROM cp_sync_job WHERE id=?", (job_id,)).fetchone()
        if not row: raise ControlPlaneError("job_not_found")
        return dict(row)

    def metrics(self) -> str:
        with Connection(self.path) as db:
            jobs=db.execute("SELECT status,count(*) n FROM cp_sync_job GROUP BY status").fetchall()
            drift=db.execute("SELECT drift_code,count(*) n FROM cp_reconciliation_difference WHERE remediation_status!='RESOLVED' GROUP BY drift_code").fetchall()
            dead=db.execute("SELECT count(*) n FROM cp_dead_letter").fetchone()
        lines=["# TYPE codestra_mapping_sync_jobs gauge"]
        lines += [f'codestra_mapping_sync_jobs{{status="{r["status"]}"}} {r["n"]}' for r in jobs]
        lines += ["# TYPE codestra_mapping_drift gauge"]
        lines += [f'codestra_mapping_drift{{code="{r["drift_code"]}"}} {r["n"]}' for r in drift]
        lines += ["# TYPE codestra_mapping_dead_letters gauge",f'codestra_mapping_dead_letters {dead["n"]}']
        return "\n".join(lines)+"\n"
