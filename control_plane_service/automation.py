"""Validated contracts for Kong-authenticated n8n campaign automation calls."""
from __future__ import annotations

from typing import Any

from .core import ControlPlaneError, Store, now_iso

ENVELOPE_FIELDS = {
    "schema_version", "event_id", "event_type", "correlation_id", "idempotency_key",
    "tenant_id", "business_unit_id", "campaign_id", "entity_type", "entity_id",
    "actor_type", "actor_id", "occurred_at", "automation_key", "payload",
}
RESULT_FIELDS = {
    "event_id", "correlation_id", "idempotency_key", "workflow_key",
    "execution_id", "status", "actions", "completed_at",
}


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
    channel = payload.get("channel")
    contact = payload.get("contact_id")
    if channel in {"sms", "email"}:
        if not contact or not store.preference_allows(tenant, str(contact), channel):
            raise ControlPlaneError("contact_policy_denied")
    return {**value, "authorized": True, "policy_checked_at": now_iso()}


def record_execution_result(store: Store, value: dict[str, Any], tenant: str):
    if not isinstance(value, dict) or RESULT_FIELDS - set(value):
        raise ControlPlaneError("invalid_execution_result")
    if value["status"] not in {"COMPLETED", "FAILED", "RETRY_PENDING", "DEAD_LETTER"}:
        raise ControlPlaneError("invalid_execution_status")
    envelope = {
        "event_id": "n8n-result-" + str(value["event_id"]),
        "source": "n8n",
        "event_type": "workflow.completed" if value["status"] == "COMPLETED" else "workflow.failed",
        "event_version": "1.0",
        "occurred_at": value["completed_at"],
        "tenant_id": tenant,
        "customer_id": None,
        "correlation_id": value["correlation_id"],
        "idempotency_key": value["idempotency_key"],
        "payload": {
            "origin_event_id": value["event_id"], "workflow_key": value["workflow_key"],
            "execution_id": value["execution_id"], "status": value["status"],
            "actions": value["actions"],
        },
        "metadata": {"gateway_authenticated": True},
    }
    # Kong has already authenticated the machine caller. Exact callback retries
    # are transport duplicates and must remain idempotent; altered payloads are
    # rejected by Store.ingest's tenant/source/idempotency digest comparison.
    return store.ingest(envelope)
