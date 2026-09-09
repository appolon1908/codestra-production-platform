"""Governed, tenant-scoped n8n business-process contracts."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from .campaign_gates import authorize_channel
from .core import ControlPlaneError, IngestResult, Store, now_iso
from .database import IntegrityError, is_postgres


ENVELOPE_FIELDS = {
    "schema_version", "event_id", "event_type", "correlation_id", "idempotency_key",
    "tenant_id", "business_unit_id", "campaign_id", "entity_type", "entity_id",
    "actor_type", "actor_id", "occurred_at", "automation_key", "payload",
}
RESULT_FIELDS = {
    "event_id", "correlation_id", "idempotency_key", "workflow_key",
    "execution_id", "status", "actions", "completed_at",
}

# Explicit business outcomes. n8n may coordinate only these Middleware-owned
# processes and may never call Odoo or a provider directly.
AUTOMATION_PLANS = {
    "telnexa.sms.submitted": ["communication.status.project"],
    "telnexa.sms.sent": ["communication.status.project"],
    "telnexa.sms.received": ["conversation.inbound.project", "crm.activity.request"],
    "telnexa.sms.delivered": ["communication.status.project"],
    "telnexa.sms.failed": ["communication.status.project", "delivery.failure.reconcile"],
    "telnexa.sms.rejected": ["communication.status.project", "delivery.failure.reconcile"],
    "telnexa.sms.expired": ["communication.status.project", "delivery.failure.reconcile"],
    "telnexa.sms.opted_out": ["contact.preference.disable", "contact.suppression.reconcile"],
    "klyrow.email.delivered": ["communication.status.project"],
    "klyrow.email.bounced": ["communication.status.project", "contact.suppression.reconcile"],
    "klyrow.email.deferred": ["communication.status.project", "delivery.failure.reconcile"],
    "klyrow.email.complained": ["communication.status.project", "contact.suppression.reconcile"],
    "klyrow.email.unsubscribed": ["contact.preference.disable", "contact.suppression.reconcile"],
    "kyqra.record.created": ["crm.enrichment.request"],
    "kyqra.job.completed": ["enrichment.job.reconcile"],
    "kyqra.job.failed": ["enrichment.job.reconcile", "delivery.failure.reconcile"],
    "customer.created": ["crm.customer.synchronize"],
    "customer.updated": ["crm.customer.synchronize"],
    "crm.lead.created": ["campaign.followup.evaluate"],
    "crm.lead.updated": ["campaign.followup.evaluate"],
    "crm.activity.created": ["agent.workqueue.reconcile"],
    "crm.followup.due.v1": ["campaign.followup.execute"],
}

SQLITE_AUTOMATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS automation_executions(
 tenant_id TEXT NOT NULL,event_id TEXT NOT NULL,workflow_key TEXT NOT NULL,
 request_hash TEXT NOT NULL,status TEXT NOT NULL,approved_actions TEXT NOT NULL,
 correlation_id TEXT NOT NULL,execution_id TEXT,started_at TEXT NOT NULL,
 completed_at TEXT,updated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,event_id,workflow_key));
CREATE TABLE IF NOT EXISTS automation_action_executions(
 tenant_id TEXT NOT NULL,event_id TEXT NOT NULL,workflow_key TEXT NOT NULL,
 action TEXT NOT NULL,request_hash TEXT NOT NULL,status TEXT NOT NULL,
 receipt TEXT NOT NULL,completed_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,event_id,workflow_key,action));
CREATE UNIQUE INDEX IF NOT EXISTS automation_executions_orchestrator
 ON automation_executions(execution_id) WHERE execution_id IS NOT NULL AND execution_id <> '';
CREATE TABLE IF NOT EXISTS automation_execution_attempts(
 execution_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,event_id TEXT NOT NULL,
 workflow_key TEXT NOT NULL,request_hash TEXT NOT NULL,started_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'RUNNING',completed_at TEXT,
 FOREIGN KEY(tenant_id,event_id,workflow_key)
 REFERENCES automation_executions(tenant_id,event_id,workflow_key));
INSERT INTO automation_execution_attempts(
 execution_id,tenant_id,event_id,workflow_key,request_hash,started_at,status,completed_at)
 SELECT execution_id,tenant_id,event_id,workflow_key,request_hash,started_at,status,completed_at
 FROM automation_executions WHERE execution_id IS NOT NULL AND execution_id <> ''
 ON CONFLICT DO NOTHING;

"""


def _ensure_embedded_schema(db: Any) -> None:
    if not is_postgres():
        db.executescript(SQLITE_AUTOMATION_SCHEMA)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _action_environment(action: str) -> str:
    return "CONTROL_PLANE_ACTION_" + "".join(
        character.upper() if character.isalnum() else "_" for character in action
    ) + "_URL"


def _action_secret() -> bytes:
    path = os.getenv("CONTROL_PLANE_AUTOMATION_ACTION_SECRET_FILE", "")
    if not path:
        raise ControlPlaneError("automation_action_secret_missing")
    try:
        secret = Path(path).read_bytes().strip()
    except OSError as exc:
        raise ControlPlaneError("automation_action_secret_unreadable") from exc
    if len(secret) < 32:
        raise ControlPlaneError("automation_action_secret_invalid")
    return secret


def _invoke_action(action: str, value: dict[str, Any], request_hash: str) -> dict[str, Any]:
    url = os.getenv(_action_environment(action), "")
    if not url:
        raise ControlPlaneError(f"automation_action_handler_missing:{action}")
    action_key = f"{value['tenant_id']}:{value['event_id']}:{value['automation_key']}:{action}"
    body = _canonical({"action": action, "idempotency_key": action_key, "event": {key: value[key] for key in sorted(ENVELOPE_FIELDS)}}).encode()
    signature = hmac.new(_action_secret(), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(url, body, {
        "Content-Type": "application/json",
        "Idempotency-Key": action_key,
        "X-Codestra-Action": action,
        "X-Codestra-Request-Hash": request_hash,
        "X-Codestra-Signature": "sha256=" + signature,
    }, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status < 200 or response.status >= 300:
                raise ControlPlaneError(f"automation_action_failed:{action}")
            receipt = json.loads(response.read())
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlPlaneError(f"automation_action_failed:{action}") from exc
    if not isinstance(receipt, dict) or receipt.get("status") != "COMPLETED":
        raise ControlPlaneError(f"automation_action_incomplete:{action}")
    if receipt.get("action") != action or receipt.get("idempotency_key") != action_key:
        raise ControlPlaneError(f"automation_action_receipt_mismatch:{action}")
    return receipt


def authorize_automation(store: Store, value: dict[str, Any], tenant: str) -> dict[str, Any]:
    if not isinstance(value, dict) or ENVELOPE_FIELDS - set(value):
        raise ControlPlaneError("invalid_automation_envelope")
    if value["schema_version"] != "1" or value["tenant_id"] != tenant:
        raise ControlPlaneError("cross_tenant_denied")
    if value["actor_type"] not in {"HUMAN", "AI", "SYSTEM"}:
        raise ControlPlaneError("invalid_actor")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise ControlPlaneError("invalid_payload")
    actions = AUTOMATION_PLANS.get(str(value["event_type"]))
    if not actions:
        raise ControlPlaneError("automation_plan_not_allowlisted")
    channel = payload.get("channel")
    contact = payload.get("contact_id")
    if channel in {"sms", "email"}:
        authorize_channel(
            {**payload, "campaign_id": value["campaign_id"], "tenant_id": tenant,
             "business_unit_id": value["business_unit_id"]},
            simulation=payload.get("dry_run") is True,
        )
        if not contact or not store.preference_allows(tenant, str(contact), channel):
            raise ControlPlaneError("contact_policy_denied")
        if value["campaign_id"] == "COD-WEB-OUT" and channel == "email":
            recipient = str(payload.get("recipient") or "").lower()
            if not payload.get("country") or not recipient:
                raise ControlPlaneError("contact_policy_denied")
            if payload.get("legal_basis") not in {
                "consent", "existing_business_relationship", "internal_test"
            }:
                raise ControlPlaneError("contact_policy_denied")
            if store.is_suppressed(tenant, "email", recipient):
                raise ControlPlaneError("contact_policy_denied")
            if payload.get("account_hold") or payload.get("campaign_hold") or payload.get("complaint"):
                raise ControlPlaneError("contact_policy_denied")
            if payload.get("sender") != "sales@codestra.co" or payload.get("reply_to") != "support@codestra.co":
                raise ControlPlaneError("contact_policy_denied")
    return {
        **value, "authorized": True, "approved_actions": actions,
        "policy_checked_at": now_iso(),
    }


def execute_automation(store: Store, value: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Durably start an allowlisted business process; exact retries are safe."""
    if not isinstance(value, dict):
        raise ControlPlaneError("automation_authorization_required")
    if value.get("tenant_id") != tenant:
        raise ControlPlaneError("cross_tenant_denied")
    # The execute boundary must not trust client-controlled authorization
    # markers. Re-run the complete policy decision from the immutable envelope.
    material = {key: value.get(key) for key in ENVELOPE_FIELDS}
    checked = authorize_automation(store, material, tenant)
    expected = checked["approved_actions"]
    if value.get("approved_actions") not in (None, expected):
        raise ControlPlaneError("automation_action_plan_mismatch")
    event_id = str(value.get("event_id") or "")
    workflow_key = str(value.get("automation_key") or "")
    if not event_id or not workflow_key:
        raise ControlPlaneError("automation_identity_required")
    material["approved_actions"] = expected
    request_hash = hashlib.sha256(_canonical(material).encode()).hexdigest()
    attempt_id = str(value.get("orchestration_execution_id") or "")
    if not attempt_id or len(attempt_id) > 255:
        raise ControlPlaneError("automation_execution_id_required")
    stamp = now_iso()
    with store.connect() as db:
        _ensure_embedded_schema(db)
        db.execute(
            """INSERT INTO automation_executions(
                 tenant_id,event_id,workflow_key,request_hash,status,approved_actions,
                 correlation_id,execution_id,started_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
            (tenant, event_id, workflow_key, request_hash, "RUNNING", _canonical(expected),
             str(value.get("correlation_id")),
             str(value.get("orchestration_execution_id") or ""), stamp, stamp),
        )
        row = db.execute(
            """SELECT request_hash,status,approved_actions,execution_id,started_at
               FROM automation_executions
               WHERE tenant_id=? AND event_id=? AND workflow_key=?""",
            (tenant, event_id, workflow_key),
        ).fetchone()
        if not row or row["request_hash"] != request_hash:
            raise ControlPlaneError("idempotency_conflict")
        # An n8n transport retry may create another execution. Bind every
        # attempt atomically without changing the business-operation hash.
        db.execute(
            """INSERT INTO automation_execution_attempts(
               execution_id,tenant_id,event_id,workflow_key,request_hash,started_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
            (attempt_id, tenant, event_id, workflow_key, request_hash, stamp),
        )
        attempt = db.execute(
            "SELECT tenant_id,event_id,workflow_key,request_hash FROM automation_execution_attempts WHERE execution_id=?",
            (attempt_id,),
        ).fetchone()
        if not attempt or tuple(attempt[key] for key in
                ("tenant_id", "event_id", "workflow_key", "request_hash")) != (
                tenant, event_id, workflow_key, request_hash):
            raise ControlPlaneError("idempotency_conflict")
    completed_actions = []
    for action in expected:
        with store.connect() as db:
            prior = db.execute(
                """SELECT request_hash,status,receipt FROM automation_action_executions
                   WHERE tenant_id=? AND event_id=? AND workflow_key=? AND action=?""",
                (tenant, event_id, workflow_key, action),
            ).fetchone()
        if prior:
            if prior["request_hash"] != request_hash or prior["status"] != "COMPLETED":
                raise ControlPlaneError("idempotency_conflict")
            receipt = json.loads(prior["receipt"])
        else:
            receipt = _invoke_action(action, value, request_hash)
            with store.connect() as db:
                db.execute(
                    """INSERT INTO automation_action_executions(
                         tenant_id,event_id,workflow_key,action,request_hash,status,receipt,completed_at)
                       VALUES(?,?,?,?,?,'COMPLETED',?,?) ON CONFLICT DO NOTHING""",
                    (tenant, event_id, workflow_key, action, request_hash,
                     _canonical(receipt), now_iso()),
                )
                persisted = db.execute(
                    """SELECT request_hash,status,receipt FROM automation_action_executions
                       WHERE tenant_id=? AND event_id=? AND workflow_key=? AND action=?""",
                    (tenant, event_id, workflow_key, action),
                ).fetchone()
            if not persisted or persisted["request_hash"] != request_hash or persisted["status"] != "COMPLETED":
                raise ControlPlaneError("idempotency_conflict")
            receipt = json.loads(persisted["receipt"])
        completed_actions.append({"type": action, "receipt": receipt})
    with store.connect() as db:
        db.execute(
            """UPDATE automation_executions SET status='ACTIONS_COMPLETED',updated_at=?
               WHERE tenant_id=? AND event_id=? AND workflow_key=? AND request_hash=? AND status!='COMPLETED'""",
            (now_iso(), tenant, event_id, workflow_key, request_hash),
        )
    return {
        **value, "business_process_status": "ACTIONS_COMPLETED",
        "executed_actions": completed_actions,
        "business_process_started_at": row["started_at"],
    }


def validate_execution_result(value: object) -> None:
    if not isinstance(value, dict) or RESULT_FIELDS - set(value):
        raise ControlPlaneError("invalid_execution_result")
    for name in RESULT_FIELDS - {"actions"}:
        item = value[name]
        if (not isinstance(item, str) or not item.strip() or len(item) > 2048
                or any(ord(char) < 32 for char in item)):
            raise ControlPlaneError("invalid_execution_result")
    if value["status"] not in {"COMPLETED", "FAILED", "RETRY_PENDING", "DEAD_LETTER"}:
        raise ControlPlaneError("invalid_execution_status")
    actions = value["actions"]
    if not isinstance(actions, list) or len(actions) > 100:
        raise ControlPlaneError("invalid_execution_result")
    for action in actions:
        if (not isinstance(action, dict) or not isinstance(action.get("type"), str)
                or not action["type"].strip() or len(action["type"]) > 128):
            raise ControlPlaneError("invalid_execution_result")
    if len({action["type"] for action in actions}) != len(actions):
        raise ControlPlaneError("invalid_execution_result")
    try:
        timestamp = datetime.fromisoformat(value["completed_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError:
        raise ControlPlaneError("invalid_completion_timestamp") from None


def record_execution_result(store: Store, value: dict[str, Any], tenant: str):
    """Atomically record one attempt result; late failures never undo success."""
    validate_execution_result(value)
    value = dict(value)
    envelope = None
    try:
        with store.connect() as db:
            _ensure_embedded_schema(db)
            if not is_postgres():
                db.execute("BEGIN IMMEDIATE")
            execution = db.execute(
                """SELECT a.tenant_id,a.event_id,a.workflow_key,a.request_hash,
                   e.correlation_id,e.approved_actions FROM automation_execution_attempts a
                   JOIN automation_executions e ON e.tenant_id=a.tenant_id
                   AND e.event_id=a.event_id AND e.workflow_key=a.workflow_key
                   WHERE a.execution_id=?""" + (" FOR UPDATE OF e" if is_postgres() else ""),
                (str(value["execution_id"]),),
            ).fetchone()
            if not execution:
                raise ControlPlaneError("automation_execution_not_found")
            # Unknown identity remains supported only for the established error
            # callback path; successful callbacks must name their bound tenant.
            if tenant != execution["tenant_id"] and not (
                    value["status"] != "COMPLETED" and tenant in {"", "unknown"}):
                raise ControlPlaneError("cross_tenant_denied")
            tenant = execution["tenant_id"]
            if value["status"] == "COMPLETED":
                for key in ("event_id", "workflow_key", "correlation_id"):
                    if str(value[key]) != execution[key]:
                        raise ControlPlaneError("automation_execution_not_found")
            else:
                value.update({key: execution[key] for key in ("event_id", "workflow_key", "correlation_id")})
            result_id = "n8n-result-" + hashlib.sha256(_canonical([
                tenant, execution["event_id"], execution["workflow_key"], str(value["execution_id"]),
            ]).encode()).hexdigest()
            envelope = {
                "event_id": result_id, "source": "n8n",
                "event_type": "workflow.completed" if value["status"] == "COMPLETED" else "workflow.failed",
                "event_version": "1.0", "occurred_at": value["completed_at"],
                "tenant_id": tenant, "customer_id": None,
                "correlation_id": value["correlation_id"], "idempotency_key": value["idempotency_key"],
                "payload": {"origin_event_id": value["event_id"], "workflow_key": value["workflow_key"],
                            "execution_id": str(value["execution_id"]), "status": value["status"],
                            "actions": value["actions"]},
                "metadata": {"gateway_authenticated": True},
            }
            # Result identity, attempt state, aggregate state and outbox commit
            # together. An altered callback loses before mutating any status.
            db.execute(
                """INSERT INTO events(event_id,tenant_id,source,event_type,
                   idempotency_key,correlation_id,envelope,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (result_id, tenant, "n8n", envelope["event_type"], value["idempotency_key"],
                 value["correlation_id"], _canonical(envelope), __import__("time").time()),
            )
            if value["status"] == "COMPLETED":
                expected = json.loads(execution["approved_actions"])
                reported = [item.get("type") for item in value["actions"] if isinstance(item, dict)]
                receipts = db.execute(
                    """SELECT action,request_hash,status FROM automation_action_executions
                       WHERE tenant_id=? AND event_id=? AND workflow_key=?""",
                    (tenant, execution["event_id"], execution["workflow_key"]),
                ).fetchall()
                if {r["action"] for r in receipts if r["status"] == "COMPLETED"
                        and r["request_hash"] == execution["request_hash"]} != set(expected):
                    raise ControlPlaneError("automation_actions_incomplete")
                if reported != expected:
                    raise ControlPlaneError("automation_action_result_mismatch")
            db.execute(
                "UPDATE automation_execution_attempts SET status=?,completed_at=? WHERE execution_id=?",
                (value["status"], value["completed_at"], str(value["execution_id"])),
            )
            db.execute(
                """UPDATE automation_executions SET status=?,completed_at=?,updated_at=?
                   WHERE tenant_id=? AND event_id=? AND workflow_key=? AND status!='COMPLETED'
                   AND (?='COMPLETED' OR NOT EXISTS (
                     SELECT 1 FROM automation_execution_attempts a
                     WHERE a.tenant_id=? AND a.event_id=? AND a.workflow_key=?
                       AND a.execution_id!=? AND a.status IN ('RUNNING','ACTIONS_COMPLETED')))""",
                (value["status"], value["completed_at"], now_iso(), tenant, execution["event_id"],
                 execution["workflow_key"], value["status"], tenant, execution["event_id"],
                 execution["workflow_key"], str(value["execution_id"])),
            )
            db.execute("INSERT INTO event_deliveries(event_id,target) VALUES(?,?)", (result_id, "odoo"))
        return IngestResult(result_id, str(value["correlation_id"]), False, "queued")
    except IntegrityError:
        replay = store.exact_event_replay(envelope) if envelope is not None else None
        if replay is None:
            raise ControlPlaneError("idempotency_conflict") from None
        return replay
