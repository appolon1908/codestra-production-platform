"""Fail-closed durable delivery of acknowledged n8n results to Odoo."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.odoo.client import OdooDeliveryClient
from app.core.automation import canonical_hash
from app.core.config import settings
from app.core.endpoint_registry import (
    RegistryResolver,
    ResolutionRequest,
    SignedSnapshotCache,
    SqlEndpointRepository,
)
from app.core.service_client import CommonServiceClient
from app.core.token_manager import ClientSecretTokenManager, TokenManager
from app.db.models import (
    BroadEventDelivery,
    IntegrationEvent,
    N8nAcknowledgement,
    N8nExecutionRegistration,
    N8nRuntimeExecution,
    N8nRuntimeResult,
    OdooResultDelivery,
)


class OdooResultError(RuntimeError):
    pass


class OdooServiceClient(Protocol):
    async def request(
        self,
        operation: str,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> httpx.Response: ...

    async def aclose(self) -> None: ...


async def deliver_result(
    session: AsyncSession,
    result_delivery_id: UUID,
    *,
    client: OdooServiceClient | None = None,
) -> dict[str, Any]:
    if not (
        settings.odoo_result_delivery_enabled
        or settings.test_syn_odoo_result_delivery_enabled
    ):
        raise OdooResultError("Odoo result delivery is disabled")
    result = await session.get(
        OdooResultDelivery, result_delivery_id, with_for_update=True
    )
    if result is None or result.status not in {"PENDING", "RETRY"}:
        raise OdooResultError("result delivery is not claimable")
    acknowledgement = (
        await session.get(N8nAcknowledgement, result.acknowledgement_id)
        if result.acknowledgement_id
        else None
    )
    runtime_result = (
        await session.get(N8nRuntimeResult, result.runtime_result_id)
        if result.runtime_result_id
        else None
    )
    runtime_execution = (
        await session.get(N8nRuntimeExecution, runtime_result.execution_id)
        if runtime_result
        else None
    )
    registration = (
        await session.scalar(
            select(N8nExecutionRegistration).where(
                N8nExecutionRegistration.registration_id
                == acknowledgement.registration_id
            )
        )
        if acknowledgement
        else None
    )
    delivery = (
        await session.get(BroadEventDelivery, acknowledgement.delivery_id)
        if acknowledgement
        else None
    )
    event = await session.get(IntegrationEvent, delivery.event_id) if delivery else None
    if runtime_result is not None and runtime_execution is not None:
        binding = approved_runtime_binding(runtime_execution, runtime_result)
        if binding is None:
            raise OdooResultError("runtime result is not an approved synthetic mapping")
        body = _runtime_result_body(result, runtime_result, runtime_execution, binding)
        correlation_id = runtime_execution.correlation_id
        causation_id = runtime_execution.causation_id
    elif (
        acknowledgement is None
        or registration is None
        or delivery is None
        or event is None
    ):
        raise OdooResultError("result source binding is incomplete")
    else:
        body = _acknowledgement_result_body(
            result, acknowledgement, registration, delivery, event
        )
        correlation_id = acknowledgement.correlation_id
        causation_id = str(acknowledgement.acknowledgement_id)
    result.status = "RESERVED"
    result.reserved_at = datetime.now(UTC)
    await session.commit()
    owns_client = client is None
    service_client = client or _build_odoo_client(session, body)
    try:
        try:
            response = await service_client.request(
                "results.create",
                body,
                idempotency_key=str(result.result_public_id),
                request_id=f"REQ-{uuid4()}",
                correlation_id=correlation_id,
                causation_id=causation_id,
                traceparent=_traceparent(correlation_id, str(result.result_public_id)),
            )
        except httpx.TransportError as exc:
            await _record_delivery_failure(
                session,
                result_delivery_id,
                error_class="ODOO_TRANSPORT_ERROR",
                retryable=True,
            )
            raise OdooResultError("Odoo result dependency unavailable") from exc
    finally:
        if owns_client:
            await service_client.aclose()
    result = await session.get(
        OdooResultDelivery, result_delivery_id, with_for_update=True
    )
    if result is None:
        raise OdooResultError("result reservation disappeared")
    if response.is_redirect:
        await _record_delivery_failure(
            session,
            result_delivery_id,
            error_class="REDIRECT_REJECTED",
            retryable=False,
        )
        raise OdooResultError("Odoo redirect rejected")
    if response.status_code not in {200, 201}:
        await _record_delivery_failure(
            session,
            result_delivery_id,
            error_class=f"HTTP_{response.status_code}",
            retryable=response.status_code in {408, 429, 500, 502, 503, 504},
        )
        raise OdooResultError("Odoo result rejected")
    try:
        accepted = response.json()
    except ValueError as exc:
        await _record_delivery_failure(
            session,
            result_delivery_id,
            error_class="INVALID_RESPONSE",
            retryable=False,
        )
        raise OdooResultError("Odoo response is invalid") from exc
    required = {
        "persisted": True,
        "result_public_id": str(result.result_public_id),
        "correlation_id": correlation_id,
    }
    if any(accepted.get(key) != value for key, value in required.items()):
        await _record_delivery_failure(
            session,
            result_delivery_id,
            error_class="RESPONSE_BINDING_MISMATCH",
            retryable=False,
        )
        raise OdooResultError("Odoo response binding mismatch")
    result.status = "DELIVERED"
    result.delivered_at = datetime.now(UTC)
    result.reserved_at = None
    result.next_attempt_at = None
    result.last_error_class = None
    result.odoo_result_inbox_id = str(
        accepted.get("result_inbox_id", accepted["result_public_id"])
    )
    result.response_hash = canonical_hash(accepted)
    await session.commit()
    return accepted


async def _record_delivery_failure(
    session: AsyncSession,
    result_delivery_id: UUID,
    *,
    error_class: str,
    retryable: bool,
) -> None:
    delivery = await session.get(
        OdooResultDelivery, result_delivery_id, with_for_update=True
    )
    if delivery is None:
        raise OdooResultError("result reservation disappeared")
    delivery.attempts += 1
    delivery.last_error_class = error_class
    delivery.reserved_at = None
    if retryable and delivery.attempts < 3:
        delivery.status = "RETRY"
        delivery.next_attempt_at = datetime.now(UTC) + timedelta(
            seconds=5 * 2 ** (delivery.attempts - 1)
        )
    else:
        delivery.status = "DEAD_LETTER"
        delivery.next_attempt_at = None
    await session.commit()


async def recover_stale_result_deliveries(
    session: AsyncSession, lease_seconds: int = 60
) -> int:
    """Return interrupted reservations to retry; Odoo idempotency prevents replay effects."""
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    now = datetime.now(UTC)
    result = await session.execute(
        update(OdooResultDelivery)
        .where(
            OdooResultDelivery.status == "RESERVED",
            OdooResultDelivery.reserved_at <= now - timedelta(seconds=lease_seconds),
        )
        .values(
            status="RETRY",
            next_attempt_at=now,
            reserved_at=None,
            attempts=OdooResultDelivery.attempts + 1,
            last_error_class="STALE_RESERVATION_RECOVERED",
        )
    )
    await session.commit()
    return int(result.rowcount or 0)


def _acknowledgement_result_body(
    result: OdooResultDelivery,
    acknowledgement: N8nAcknowledgement,
    registration: N8nExecutionRegistration,
    delivery: BroadEventDelivery,
    event: IntegrationEvent,
) -> dict[str, Any]:
    payload = event.payload_json
    return {
        "schema_version": "1.0",
        "result_public_id": str(result.result_public_id),
        "delivery_id": str(delivery.delivery_id),
        "event_id": acknowledgement.event_id,
        "registration_id": str(registration.registration_id),
        "acknowledgement_id": str(acknowledgement.acknowledgement_id),
        "correlation_id": acknowledgement.correlation_id,
        "workflow_id": acknowledgement.workflow_id,
        "workflow_version": acknowledgement.workflow_version,
        "execution_id": acknowledgement.execution_id,
        "execution_status": acknowledgement.execution_status,
        "result_classification": acknowledgement.result_classification,
        "result_hash": f"sha256:{acknowledgement.result_hash}",
        "originating_outbox_public_id": result.originating_outbox_public_id,
        "organization_public_id": str(payload.get("organization_public_id", "")),
        "business_unit_public_id": str(payload.get("business_unit_public_id", "")),
        "campaign_public_id": str(payload.get("campaign_public_id", "")),
        "source_system": "codestra-middleware",
        "source_environment": settings.environment,
        "policy_hash": f"sha256:{acknowledgement.policy_hash}",
        "acknowledged_at": acknowledgement.persisted_at.isoformat(),
        "reconciliation_status": "RECONCILED",
        "payload": {"summary": "internal reconciliation completed"},
    }


def approved_runtime_binding(
    execution: N8nRuntimeExecution,
    runtime_result: N8nRuntimeResult | None = None,
) -> dict[str, str] | None:
    if not is_test_syn_odoo_execution(execution):
        return None
    if execution.payload_json.get("synthetic") is not True:
        return None
    binding = {
        "organization_public_id": settings.test_syn_odoo_organization_public_id,
        "business_unit_public_id": settings.test_syn_odoo_business_unit_public_id,
        "campaign_public_id": settings.test_syn_odoo_campaign_public_id,
        "originating_outbox_public_id": settings.test_syn_odoo_outbox_public_id,
    }
    if any(not value or len(value) > 128 for value in binding.values()):
        return None
    if runtime_result is not None:
        document = runtime_result.result_json
        result = document.get("result")
        if (
            document.get("schema_version") != "codestra.n8n.result.v1"
            or document.get("status") != "completed"
            or not isinstance(result, dict)
            or set(result) != {"synthetic", "event_id"}
            or result.get("synthetic") is not True
            or result.get("event_id") != execution.event_id
        ):
            return None
    return binding


def is_test_syn_odoo_execution(execution: N8nRuntimeExecution) -> bool:
    return bool(
        settings.test_syn_odoo_result_delivery_enabled
        and settings.environment == "staging"
        and execution.tenant_id == settings.test_syn_odoo_tenant_id
        and execution.workflow_code == settings.test_syn_odoo_workflow_code
        and execution.workflow_version == settings.test_syn_odoo_workflow_version
        and execution.event_type == settings.test_syn_odoo_event_type
        and execution.event_id == settings.test_syn_odoo_event_id
        and execution.correlation_id == settings.test_syn_odoo_correlation_id
    )


def _runtime_result_body(
    result: OdooResultDelivery,
    runtime_result: N8nRuntimeResult,
    execution: N8nRuntimeExecution,
    binding: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "result_public_id": str(result.result_public_id),
        "delivery_id": str(result.result_delivery_id),
        "event_id": execution.event_id,
        "registration_id": str(execution.execution_id),
        "acknowledgement_id": str(runtime_result.result_id),
        "correlation_id": execution.correlation_id,
        "causation_id": execution.causation_id,
        "workflow_id": execution.workflow_code,
        "workflow_version": execution.workflow_version,
        "execution_id": str(execution.execution_id),
        "execution_status": "SUCCEEDED",
        "result_classification": "TEST_SYN_RUNTIME_COMPLETED",
        "result_hash": f"sha256:{runtime_result.result_hash}",
        "originating_outbox_public_id": binding["originating_outbox_public_id"],
        "organization_public_id": binding["organization_public_id"],
        "business_unit_public_id": binding["business_unit_public_id"],
        "campaign_public_id": binding["campaign_public_id"],
        "source_system": "codestra-middleware",
        "source_environment": "staging",
        "policy_hash": f"sha256:{canonical_hash({'mapping': 'TEST_SYN_RUNTIME_V1'})}",
        "acknowledged_at": runtime_result.persisted_at.isoformat(),
        "reconciliation_status": "RECONCILED",
        "payload": {"summary": "TEST_SYN governed runtime completed"},
    }


def _traceparent(correlation_id: str, result_public_id: str) -> str:
    trace_id = canonical_hash({"correlation_id": correlation_id})[:32]
    span_id = canonical_hash({"result_public_id": result_public_id})[:16]
    return f"00-{trace_id}-{span_id}-01"


def _build_odoo_client(
    session: AsyncSession, payload: dict[str, Any]
) -> OdooDeliveryClient:
    async def load_private_key(reference: str) -> str:
        if reference != settings.odoo_service_credential_reference:
            raise OdooResultError("Odoo credential reference is not approved")
        path = Path(settings.odoo_service_private_key_file)
        if not path.is_absolute() or not path.is_file():
            raise OdooResultError("Odoo service private key is unavailable")
        return path.read_text()

    async def load_client_secret(reference: str) -> str:
        if reference != settings.odoo_service_credential_reference:
            raise OdooResultError("Odoo credential reference is not approved")
        path = Path(settings.odoo_results_client_secret_file)
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise OdooResultError("Odoo client secret is unavailable")
        value = path.read_text().strip()
        if path.stat().st_mode & 0o007 or len(value) < 32:
            raise OdooResultError("Odoo client secret is invalid")
        return value

    ca_path = Path(settings.odoo_results_ca_file)
    if (
        not ca_path.is_absolute()
        or not ca_path.is_file()
        or ca_path.is_symlink()
        or ca_path.stat().st_mode & 0o022
    ):
        raise OdooResultError("Odoo internal CA is unavailable or unsafe")

    token_manager: TokenManager | ClientSecretTokenManager
    if settings.odoo_results_client_secret_file:
        token_manager = ClientSecretTokenManager(
            settings.odoo_results_client_id, load_client_secret
        )
    else:
        token_manager = TokenManager(settings.odoo_results_client_id, load_private_key)

    cache = SignedSnapshotCache(
        Redis.from_url(settings.redis_url, decode_responses=True),
        settings.load_registry_snapshot_key(),
        l1_ttl_seconds=settings.registry_l1_ttl_seconds,
        l2_ttl_seconds=settings.registry_l2_ttl_seconds,
        stale_grace_seconds=settings.registry_stale_grace_seconds,
    )
    return OdooDeliveryClient(
        service_client=CommonServiceClient(
            RegistryResolver(SqlEndpointRepository(session), cache),
            token_manager,
            token_endpoint_key=ResolutionRequest(
                environment=settings.environment,
                service_key="identity",
                endpoint_key="oauth.token",
            ),
            verify=str(ca_path),
        ),
        environment=settings.environment,
        organization_public_id=str(payload["organization_public_id"]),
        business_unit_public_id=str(payload["business_unit_public_id"]),
        campaign_public_id=str(payload["campaign_public_id"]),
    )


async def claim_result_delivery(session: AsyncSession) -> OdooResultDelivery | None:
    if not (
        settings.odoo_result_delivery_enabled
        or settings.test_syn_odoo_result_delivery_enabled
    ):
        return None
    statement = (
        select(OdooResultDelivery)
        .where(
            OdooResultDelivery.status.in_({"PENDING", "RETRY"}),
            (OdooResultDelivery.next_attempt_at.is_(None))
            | (OdooResultDelivery.next_attempt_at <= datetime.now(UTC)),
        )
        .order_by(OdooResultDelivery.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not settings.odoo_result_delivery_enabled:
        statement = statement.where(OdooResultDelivery.runtime_result_id.is_not(None))
    result = await session.scalar(statement)
    return result
