"""Governed, tenant-scoped n8n business-process contracts."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .campaign_gates import authorize_channel
from .core import ControlPlaneError, Store, now_iso
from .database import is_postgres


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
"""


def _ensure_embedded_schema(db: Any) -> None:
    if not is_postgres():
        db.executescript(SQLITE_AUTOMATION_SCHEMA)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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
    if not isinstance(value, dict) or value.get("authorized") is not True:
        raise ControlPlaneError("automation_authorization_required")
    if value.get("tenant_id") != tenant:
        raise ControlPlaneError("cross_tenant_denied")
    expected = AUTOMATION_PLANS.get(str(value.get("event_type")))
    if not expected or value.get("approved_actions") != expected:
        raise ControlPlaneError("automation_action_plan_mismatch")
    event_id = str(value.get("event_id") or "")
    workflow_key = str(value.get("automation_key") or "")
    if not event_id or not workflow_key:
        raise ControlPlaneError("automation_identity_required")
    material = {key: value[key] for key in ENVELOPE_FIELDS}
    material["approved_actions"] = expected
    request_hash = hashlib.sha256(_canonical(material).encode()).hexdigest()
    stamp = now_iso()
    with store.connect() as db:
        _ensure_embedded_schema(db)
        db.execute(
            """INSERT INTO automation_executions(
                 tenant_id,event_id,workflow_key,request_hash,status,approved_actions,
                 correlation_id,started_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
            (tenant, event_id, workflow_key, request_hash, "RUNNING", _canonical(expected),
             str(value.get("correlation_id")), stamp, stamp),
        )
        row = db.execute(
            """SELECT request_hash,status,approved_actions,started_at
               FROM automation_executions
               WHERE tenant_id=? AND event_id=? AND workflow_key=?""",
            (tenant, event_id, workflow_key),
        ).fetchone()
    if not row or row["request_hash"] != request_hash:
        raise ControlPlaneError("idempotency_conflict")
    return {
        **value, "business_process_status": row["status"],
        "executed_actions": json.loads(row["approved_actions"]),
        "business_process_started_at": row["started_at"],
    }


def record_execution_result(store: Store, value: dict[str, Any], tenant: str):
    if not isinstance(value, dict) or RESULT_FIELDS - set(value):
        raise ControlPlaneError("invalid_execution_result")
    if value["status"] not in {"COMPLETED", "FAILED", "RETRY_PENDING", "DEAD_LETTER"}:
        raise ControlPlaneError("invalid_execution_status")
    with store.connect() as db:
        _ensure_embedded_schema(db)
        if value["status"] != "COMPLETED":
            stamp = now_iso()
            failure_hash = "failure:" + hashlib.sha256(_canonical(value).encode()).hexdigest()
            db.execute(
                """INSERT INTO automation_executions(
                     tenant_id,event_id,workflow_key,request_hash,status,approved_actions,
                     correlation_id,execution_id,started_at,completed_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                (tenant, str(value["event_id"]), str(value["workflow_key"]),
                 failure_hash,
                 value["status"], "[]", str(value["correlation_id"]),
                 str(value["execution_id"]), stamp, value["completed_at"], stamp),
            )
            prior = db.execute(
                """SELECT request_hash FROM automation_executions
                   WHERE tenant_id=? AND event_id=? AND workflow_key=?""",
                (tenant, str(value["event_id"]), str(value["workflow_key"])),
            ).fetchone()
            if prior and str(prior["request_hash"]).startswith("failure:") and prior["request_hash"] != failure_hash:
                raise ControlPlaneError("idempotency_conflict")
        changed = db.execute(
            """UPDATE automation_executions
               SET status=?,execution_id=?,completed_at=?,updated_at=?
               WHERE tenant_id=? AND event_id=? AND workflow_key=?""",
            (value["status"], str(value["execution_id"]), value["completed_at"], now_iso(),
             tenant, str(value["event_id"]), str(value["workflow_key"])),
        ).rowcount
    if changed != 1:
        raise ControlPlaneError("automation_execution_not_found")
    envelope = {
        "event_id": "n8n-result-" + str(value["event_id"]),
        "source": "n8n",
        "event_type": "workflow.completed" if value["status"] == "COMPLETED" else "workflow.failed",
        "event_version": "1.0", "occurred_at": value["completed_at"],
        "tenant_id": tenant, "customer_id": None,
        "correlation_id": value["correlation_id"], "idempotency_key": value["idempotency_key"],
        "payload": {
            "origin_event_id": value["event_id"], "workflow_key": value["workflow_key"],
            "execution_id": value["execution_id"], "status": value["status"],
            "actions": value["actions"],
        },
        "metadata": {"gateway_authenticated": True},
    }
    return store.ingest(envelope)
