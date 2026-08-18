"""Database-authoritative telephony allocation and lifecycle API."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.telephony import AUTHORITATIVE_SOURCES, ExtensionState, audit_extension
from app.db.models import (
    TelephonyExtensionPool,
    TelephonyExtensionReservation,
    TelephonyProvisioningSaga,
)
from app.db.session import get_session

router = APIRouter(prefix="/v1/telephony", tags=["telephony"])


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extension: int = Field(ge=1000, le=9999)
    evidence: dict[str, str]


class ReserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    business_unit: str = Field(min_length=1, max_length=64)
    role_class: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=16, max_length=256)
    evidence_by_extension: dict[int, dict[str, str]]
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


class ProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    employee_id: str = Field(min_length=1, max_length=128)
    business_unit: str = Field(min_length=1, max_length=64)
    campaign: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=16, max_length=256)
    approved_odoo_request: bool
    record_environment: Literal["PRODUCTION", "STAGING", "TEST"] = "PRODUCTION"
    test_run_id: str | None = Field(default=None, min_length=1, max_length=128)
    causation_id: str | None = Field(default=None, min_length=1, max_length=128)
    policy_hash: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def validate_trace_binding(payload: ProvisionRequest) -> None:
    if payload.record_environment in {"TEST", "STAGING"}:
        if payload.business_unit != "BU-400-COD" or payload.campaign != "CMP-400-COD":
            raise HTTPException(422, "test trace scope mismatch")
        if (
            not payload.test_run_id
            or not payload.causation_id
            or not payload.policy_hash
        ):
            raise HTTPException(422, "complete test trace binding required")
    elif any((payload.test_run_id, payload.causation_id, payload.policy_hash)):
        raise HTTPException(422, "test trace binding is prohibited in production")


@router.post("/extensions/audit")
async def audit(payload: AuditRequest):
    result = audit_extension(payload.extension, payload.evidence)
    return {
        "extension": result.extension,
        "classification": result.classification,
        "evidence_hash": result.evidence_hash,
        "missing_sources": result.missing_sources,
        "collision_sources": result.collision_sources,
    }


@router.get("/extensions/pools")
async def pools(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(TelephonyExtensionPool)
            .where(TelephonyExtensionPool.active.is_(True))
            .order_by(TelephonyExtensionPool.range_start)
        )
    ).scalars()
    return [
        {
            "code": row.code,
            "business_unit": row.business_unit,
            "role_class": row.role_class,
            "start": row.range_start,
            "end": row.range_end,
        }
        for row in rows
    ]


@router.get("/extensions/availability")
async def availability(extension: int, evidence_complete: bool = False):
    # A bare range check is never availability evidence.
    if extension in {1001, 6101}:
        classification = ExtensionState.EXCLUDED
    else:
        classification = ExtensionState.UNKNOWN_REQUIRES_REVIEW
    return {
        "extension": extension,
        "classification": classification,
        "evidence_complete": evidence_complete and False,
    }


@router.post("/extensions/reserve", status_code=201)
async def reserve(
    payload: ReserveRequest, session: AsyncSession = Depends(get_session)
):
    key_hash = _hash(payload.idempotency_key)
    replay = (
        await session.execute(
            select(TelephonyExtensionReservation).where(
                TelephonyExtensionReservation.idempotency_hash == key_hash
            )
        )
    ).scalar_one_or_none()
    if replay:
        return {
            "reservation_id": replay.id,
            "extension": replay.extension,
            "state": replay.state,
            "replayed": True,
        }
    pool = (
        await session.execute(
            select(TelephonyExtensionPool)
            .where(
                TelephonyExtensionPool.business_unit == payload.business_unit,
                TelephonyExtensionPool.role_class == payload.role_class,
                TelephonyExtensionPool.active.is_(True),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not pool:
        raise HTTPException(422, "no matching active extension pool")
    active = set(
        (
            await session.execute(
                select(TelephonyExtensionReservation.extension)
                .where(
                    TelephonyExtensionReservation.extension.between(
                        pool.range_start, pool.range_end
                    ),
                    TelephonyExtensionReservation.state.in_(
                        (
                            "RESERVED",
                            "DISABLED_READY",
                            "ACTIVE",
                            "SUSPENDED",
                            "COOLDOWN",
                        )
                    ),
                )
                .with_for_update()
            )
        ).scalars()
    )
    selected = None
    evidence_hash = None
    for extension in range(pool.range_start, pool.range_end + 1):
        if extension in active or extension in {1001, 6101}:
            continue
        result = audit_extension(
            extension, payload.evidence_by_extension.get(extension, {})
        )
        if result.classification == ExtensionState.AVAILABLE:
            selected, evidence_hash = extension, result.evidence_hash
            break
    if selected is None:
        raise HTTPException(409, "no fully-audited extension is available")
    row = TelephonyExtensionReservation(
        extension=selected,
        employee_id=payload.employee_id,
        request_id=payload.request_id,
        pool_id=pool.id,
        idempotency_hash=key_hash,
        evidence_hash=evidence_hash,
        expires_at=datetime.now(UTC) + timedelta(seconds=payload.ttl_seconds),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            409, "concurrent reservation conflict; retry safely"
        ) from exc
    return {
        "reservation_id": row.id,
        "extension": selected,
        "state": row.state,
        "replayed": False,
    }


@router.post("/provisioning", status_code=202)
async def provision(
    payload: ProvisionRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    if not payload.approved_odoo_request:
        raise HTTPException(403, "approved Odoo request required")
    validate_trace_binding(payload)
    key_hash = _hash(payload.idempotency_key)
    existing = (
        await session.execute(
            select(TelephonyProvisioningSaga).where(
                TelephonyProvisioningSaga.idempotency_hash == key_hash
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {
            "request_id": existing.request_id,
            "state": existing.state,
            "correlation_id": existing.correlation_id,
            "replayed": True,
        }
    row = TelephonyProvisioningSaga(
        request_id=payload.request_id,
        employee_id=payload.employee_id,
        business_unit=payload.business_unit,
        campaign=payload.campaign,
        role=payload.role,
        state="APPROVED",
        idempotency_hash=key_hash,
        correlation_id=getattr(request.state, "correlation_id", str(uuid4())),
        record_environment=payload.record_environment,
        test_run_id=payload.test_run_id,
        causation_id=payload.causation_id,
        policy_hash=payload.policy_hash,
        approved_odoo_request=True,
        completed_steps=[],
    )
    session.add(row)
    await session.commit()
    return {
        "request_id": row.request_id,
        "state": row.state,
        "correlation_id": row.correlation_id,
        "replayed": False,
        "production_mutation": settings.live_writes_enabled,
    }


@router.get("/provisioning/{request_id}")
async def status(request_id: str, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(
            select(TelephonyProvisioningSaga).where(
                TelephonyProvisioningSaga.request_id == request_id
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "provisioning request not found")
    return {
        "request_id": row.request_id,
        "employee_id": row.employee_id,
        "extension": row.extension,
        "state": row.state,
        "correlation_id": row.correlation_id,
        "completed_steps": row.completed_steps,
        "version": row.version,
    }


async def _fail_closed_action(
    request_id: str, action: str, session: AsyncSession
) -> dict:
    row = (
        await session.execute(
            select(TelephonyProvisioningSaga)
            .where(TelephonyProvisioningSaga.request_id == request_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "provisioning request not found")
    if action in {"activate", "deprovision"} and not settings.live_writes_enabled:
        raise HTTPException(503, f"{action} kill switch is closed")
    return {
        "request_id": request_id,
        "state": row.state,
        "action": action,
        "accepted": False,
    }


@router.post("/provisioning/{request_id}/activate")
async def activate(request_id: str, session: AsyncSession = Depends(get_session)):
    return await _fail_closed_action(request_id, "activate", session)


@router.post("/provisioning/{request_id}/suspend")
async def suspend(request_id: str, session: AsyncSession = Depends(get_session)):
    return await _fail_closed_action(request_id, "suspend", session)


@router.post("/provisioning/{request_id}/deprovision")
async def deprovision(request_id: str, session: AsyncSession = Depends(get_session)):
    return await _fail_closed_action(request_id, "deprovision", session)


@router.post("/provisioning/{request_id}/rollback")
async def rollback(request_id: str, session: AsyncSession = Depends(get_session)):
    return await _fail_closed_action(request_id, "rollback", session)


@router.post("/reconcile")
async def reconcile():
    return {
        "mode": "report-only",
        "state": "accepted",
        "authoritative_sources": sorted(AUTHORITATIVE_SOURCES),
    }
