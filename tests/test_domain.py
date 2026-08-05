from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from codestra_vicidial.domain import ExtensionRecord, TelephonyEvent


def test_telephony_event_requires_tenant_workspace_and_aware_timestamp():
    event = TelephonyEvent(
        event_id=uuid4(), event_type="call.started", tenant_id="tenant-a",
        workspace_id="workspace-a", timestamp="2026-08-05T04:00:00Z",
        correlation_id="call-1", idempotency_key="call-1:started",
    )
    assert event.timestamp.utcoffset().total_seconds() == 0
    with pytest.raises(ValidationError):
        TelephonyEvent(
            event_id=uuid4(), event_type="call.started", tenant_id="tenant-a",
            workspace_id="workspace-a", timestamp=datetime(2026, 8, 5),
            correlation_id="call-1", idempotency_key="call-1:started",
        )


def test_extension_registry_rejects_unallocated_range():
    with pytest.raises(ValidationError):
        ExtensionRecord(
            extension=6700, tenant="t", workspace="w", department="d",
            device="pjsip", status="ACTIVE", purpose="invalid range",
            created_at="2026-08-05T04:00:00Z",
        )

