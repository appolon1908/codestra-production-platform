"""Explicit Odoo/n8n integration gateway routes.

Existing event and callback routes remain the implementation of record; these
namespaces make the ownership boundary unambiguous. Command execution is
fail-closed until the approved Odoo adapter and live-write flag are enabled.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1, max_length=128)
    command_type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)


class CallbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)


def _require_replay_headers(timestamp: str | None, nonce: str | None, signature: str | None) -> None:
    if not timestamp or not nonce or not signature:
        raise HTTPException(401, "timestamp, nonce, and signature are required")
    try:
        if abs(datetime.now(timezone.utc).timestamp() - float(timestamp)) > settings.signature_ttl_seconds:
            raise HTTPException(401, "request timestamp expired")
    except ValueError as exc:
        raise HTTPException(401, "request timestamp invalid") from exc


@router.get("/odoo/health")
async def odoo_health() -> dict[str, str]:
    return {"status": "ok", "gateway": "codestra-middleware", "provider": "odoo"}


@router.get("/odoo/readiness")
async def odoo_readiness() -> dict[str, str]:
    return {"status": "ready" if settings.auth_ready else "not-ready", "provider": "odoo"}


@router.post("/odoo/commands", status_code=202)
async def odoo_command(
    body: CommandRequest,
    x_timestamp: str | None = Header(None, alias="X-Timestamp"),
    x_nonce: str | None = Header(None, alias="X-Nonce"),
    x_signature: str | None = Header(None, alias="X-Signature"),
) -> dict[str, str]:
    _require_replay_headers(x_timestamp, x_nonce, x_signature)
    if not settings.odoo_automation_writes_enabled:
        raise HTTPException(503, "Odoo automation writes are disabled")
    return {"command_id": body.command_id, "status": "queued"}


@router.get("/odoo/commands/{command_id}")
async def odoo_command_status(command_id: str) -> dict[str, str]:
    return {"command_id": command_id, "status": "not_configured"}


@router.post("/n8n/dispatch", status_code=202)
async def n8n_dispatch(
    body: CommandRequest,
    x_timestamp: str | None = Header(None, alias="X-Timestamp"),
    x_nonce: str | None = Header(None, alias="X-Nonce"),
    x_signature: str | None = Header(None, alias="X-Signature"),
) -> dict[str, str]:
    _require_replay_headers(x_timestamp, x_nonce, x_signature)
    if not settings.n8n_event_delivery_enabled:
        raise HTTPException(503, "n8n delivery is disabled")
    return {"command_id": body.command_id, "status": "queued"}


@router.post("/n8n/results", status_code=202)
async def n8n_result(body: CallbackResult) -> dict[str, str]:
    return {"accepted": "true", "command_id": body.command_id, "status": body.status}


@router.post("/n8n/errors", status_code=202)
async def n8n_error(body: CallbackResult) -> dict[str, str]:
    return {"accepted": "true", "command_id": body.command_id, "status": body.status}


@router.post("/n8n/reconciliation", status_code=202)
async def n8n_reconciliation(body: CommandRequest) -> dict[str, str]:
    return {"accepted": "true", "command_id": body.command_id, "status": "recorded"}
