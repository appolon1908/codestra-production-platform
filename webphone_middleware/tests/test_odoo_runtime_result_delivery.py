from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from app.adapters.odoo.results import (
    OdooResultError,
    _build_odoo_client,
    deliver_result,
    recover_stale_result_deliveries,
)
from app.core.config import settings
from app.db.models import N8nRuntimeExecution, N8nRuntimeResult, OdooResultDelivery


EXECUTION_ID = UUID("11111111-1111-1111-1111-111111111111")
RESULT_ID = UUID("22222222-2222-2222-2222-222222222222")
DELIVERY_ID = UUID("33333333-3333-3333-3333-333333333333")
PUBLIC_ID = UUID("44444444-4444-4444-4444-444444444444")


def configure_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "environment": "staging",
        "test_syn_odoo_result_delivery_enabled": True,
        "test_syn_odoo_event_type": "test.synthetic.requested",
        "test_syn_odoo_event_id": "TEST_SYN_EVENT_001",
        "test_syn_odoo_correlation_id": "TEST_SYN_CORRELATION_001",
        "test_syn_odoo_organization_public_id": "ORG-TEST-SYN",
        "test_syn_odoo_business_unit_public_id": "BU-TEST-SYN",
        "test_syn_odoo_campaign_public_id": "CAMPAIGN-TEST-SYN",
        "test_syn_odoo_outbox_public_id": "OUTBOX-TEST-SYN",
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


def records():
    execution = N8nRuntimeExecution(
        execution_id=EXECUTION_ID,
        tenant_id="TEST_SYN_TENANT",
        event_id="TEST_SYN_EVENT_001",
        event_type="test.synthetic.requested",
        source_event_id="TEST_SYN_SOURCE_001",
        workflow_code="TEST_SYN_ROUTER",
        workflow_version="1",
        correlation_id="TEST_SYN_CORRELATION_001",
        causation_id="TEST_SYN_CAUSATION_001",
        trace_id="0123456789abcdef0123456789abcdef",
        idempotency_key_hash="a" * 64,
        payload_hash="b" * 64,
        payload_json={"synthetic": True},
        status="COMPLETED",
        timeout_at=datetime.now(UTC),
    )
    runtime_result = N8nRuntimeResult(
        result_id=RESULT_ID,
        execution_id=EXECUTION_ID,
        tenant_id="TEST_SYN_TENANT",
        workflow_code="TEST_SYN_ROUTER",
        result_hash="c" * 64,
        status="COMPLETED",
        result_json={
            "schema_version": "codestra.n8n.result.v1",
            "status": "completed",
            "result": {"synthetic": True, "event_id": "TEST_SYN_EVENT_001"},
        },
        occurred_at=datetime.now(UTC),
        persisted_at=datetime.now(UTC),
    )
    delivery = OdooResultDelivery(
        result_delivery_id=DELIVERY_ID,
        runtime_result_id=RESULT_ID,
        result_public_id=PUBLIC_ID,
        originating_outbox_public_id="OUTBOX-TEST-SYN",
        request_hash="d" * 64,
        status="PENDING",
        attempts=0,
    )
    return execution, runtime_result, delivery


class SequenceClient:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses

    async def request(self, operation, payload, **kwargs):
        assert operation == "results.create"
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self) -> None:
        return None


def session_for(execution, runtime_result, delivery):
    session = AsyncMock()

    async def get(model, identity, **kwargs):
        if model is OdooResultDelivery and identity == DELIVERY_ID:
            return delivery
        if model is N8nRuntimeResult and identity == RESULT_ID:
            return runtime_result
        if model is N8nRuntimeExecution and identity == EXECUTION_ID:
            return execution
        return None

    session.get.side_effect = get
    session.scalar.return_value = None
    return session


def test_runtime_odoo_client_fails_closed_without_internal_ca(monkeypatch, tmp_path):
    secret = tmp_path / "client-secret"
    secret.write_text("s" * 64)
    secret.chmod(0o600)
    monkeypatch.setattr(settings, "odoo_results_client_secret_file", str(secret))
    monkeypatch.setattr(settings, "odoo_results_ca_file", "")
    with pytest.raises(OdooResultError, match="internal CA"):
        _build_odoo_client(AsyncMock(), {"organization_public_id": "ORG"})


def test_runtime_odoo_client_rejects_world_writable_internal_ca(
    monkeypatch, tmp_path
):
    secret = tmp_path / "client-secret"
    secret.write_text("s" * 64)
    secret.chmod(0o600)
    ca = tmp_path / "ca.crt"
    ca.write_text("certificate")
    ca.chmod(0o666)
    monkeypatch.setattr(settings, "odoo_results_client_secret_file", str(secret))
    monkeypatch.setattr(settings, "odoo_results_ca_file", str(ca))
    with pytest.raises(OdooResultError, match="internal CA"):
        _build_odoo_client(AsyncMock(), {"organization_public_id": "ORG"})


@pytest.mark.asyncio
async def test_temporary_odoo_failure_retries_then_delivers_once(monkeypatch):
    configure_mapping(monkeypatch)
    execution, runtime_result, delivery = records()
    session = session_for(execution, runtime_result, delivery)
    client = SequenceClient(
        [
            httpx.Response(503),
            httpx.Response(
                201,
                json={
                    "persisted": True,
                    "idempotency_status": "NEW",
                    "result_public_id": str(PUBLIC_ID),
                    "correlation_id": execution.correlation_id,
                },
            ),
        ]
    )

    with pytest.raises(OdooResultError, match="rejected"):
        await deliver_result(session, DELIVERY_ID, client=client)
    assert delivery.status == "RETRY"
    assert delivery.attempts == 1

    delivery.next_attempt_at = None
    accepted = await deliver_result(session, DELIVERY_ID, client=client)
    assert accepted["idempotency_status"] == "NEW"
    assert delivery.status == "DELIVERED"
    assert delivery.attempts == 1
    assert delivery.last_error_class is None
    assert delivery.odoo_result_inbox_id == str(PUBLIC_ID)


@pytest.mark.asyncio
async def test_transport_failure_retains_durable_retry(monkeypatch):
    configure_mapping(monkeypatch)
    execution, runtime_result, delivery = records()
    session = session_for(execution, runtime_result, delivery)
    client = SequenceClient([httpx.ConnectError("synthetic outage")])

    with pytest.raises(OdooResultError, match="unavailable"):
        await deliver_result(session, DELIVERY_ID, client=client)
    assert delivery.status == "RETRY"
    assert delivery.last_error_class == "ODOO_TRANSPORT_ERROR"


@pytest.mark.asyncio
async def test_stale_reservation_recovery_is_durable():
    session = AsyncMock()
    session.execute.return_value.rowcount = 1
    assert await recover_stale_result_deliveries(session, lease_seconds=30) == 1
    session.commit.assert_awaited_once()
