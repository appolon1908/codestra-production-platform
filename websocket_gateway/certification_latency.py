"""Pure source-testable JetStream delivery sampling; never contacts a service on import."""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

MINIMUM_SAMPLES = 250
THRESHOLD_MS = 500.0
SCOPE_FIELDS = ("tenant_id", "campaign_id", "agent_id")


def latency_summary(samples: Sequence[float]) -> dict[str, Any]:
    if len(samples) < MINIMUM_SAMPLES:
        raise ValueError("at least 250 measured deliveries are required")
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("latency samples must be finite nonnegative numbers")
    ordered = sorted(samples)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return {
        "P95_DELIVERY_LATENCY": "PASS" if p95 < THRESHOLD_MS else "FAIL",
        "P95_DELIVERY_LATENCY_MS": round(p95, 3),
        "DELIVERY_SAMPLE_COUNT": len(samples),
        "DELIVERY_PERCENTILE_METHOD": "nearest-rank-ceil(0.95*N)",
        "DELIVERY_MEASUREMENT_PATH": "JetStream PubAck and scoped WebSocket receive",
        "MAX_DELIVERY_LATENCY_MS": round(ordered[-1], 3),
    }


def validate_load_scopes(identities: Sequence[dict[str, Any]]) -> None:
    if len(identities) < MINIMUM_SAMPLES:
        raise ValueError("at least 250 distinct authorized identities are required")
    seen: set[tuple[str, ...]] = set()
    for identity in identities:
        if not isinstance(identity, dict) or any(not isinstance(identity.get(key), str) or not identity[key].strip() for key in SCOPE_FIELDS):
            raise ValueError("invalid load identity")
        scope = tuple(identity[key] for key in SCOPE_FIELDS)
        if scope in seen:
            raise ValueError("duplicate load identity")
        seen.add(scope)


async def measure_delivery_batch(
    sockets: Sequence[Any], documents: Sequence[dict[str, Any]],
    publish: Callable[[dict[str, Any]], Awaitable[int]], *, timeout: float = 10.0,
) -> list[float]:
    """One measured canonical event per distinct connected authorized scope.

    Scope, event and stream cursor must match, including PubAck. No timeout or
    malformed delivery may be dropped to improve the reported percentile.
    """
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("delivery timeout must be finite and positive")
    validate_load_scopes(documents)
    if len(sockets) != len(documents):
        raise ValueError("one connected socket per load identity is required")
    if len({doc["event_id"] for doc in documents}) != len(documents):
        raise ValueError("duplicate load event identity")

    async def measure(socket: Any, document: dict[str, Any]) -> float:
        started = time.perf_counter()
        cursor = await publish(document)
        value = json.loads(await socket.recv())
        if (not isinstance(value, dict) or value.get("event_id") != document["event_id"]
                or any(value.get(key) != document[key] for key in SCOPE_FIELDS)
                or type(cursor) is not int or cursor < 1
                or type(value.get("cursor")) is not int or value["cursor"] != cursor):
            raise ValueError("delivery event, stream cursor or authorized scope mismatch")
        return (time.perf_counter() - started) * 1000

    tasks = [asyncio.create_task(asyncio.wait_for(measure(socket, doc), timeout)) for socket, doc in zip(sockets, documents)]
    try:
        return list(await asyncio.gather(*tasks))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def canonical_calling_envelope(document: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Generate only contract-owned fields; UI payload cannot override identity."""
    import re
    import uuid
    from datetime import datetime
    event_type = {
        'call.ringing': 'telephony.call.ringing.v1',
        'call.answered': 'telephony.call.answered.v1',
        'call.connected': 'telephony.call.connected.v1',
        'agent.ready': 'telephony.agent.status-changed.v1',
    }[document['type']]
    for name in ('event_id', 'call_id', 'correlation_id'):
        if not isinstance(document[name], str) or str(uuid.UUID(document[name])) != document[name]:
            raise ValueError('canonical calling event requires UUID identities')
    for name in SCOPE_FIELDS:
        if not isinstance(document[name], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', document[name]):
            raise ValueError('invalid scoped JetStream subject token')
    business_unit = document.get('business_unit_id')
    if not isinstance(business_unit, str) or not 1 <= len(business_unit) <= 128:
        raise ValueError('invalid canonical business unit')
    timestamp = datetime.fromisoformat(document['timestamp'].replace('Z', '+00:00'))
    if timestamp.tzinfo is None or type(document['sequence']) is not int or document['sequence'] < 1:
        raise ValueError('invalid calling timestamp or sequence')
    value = {
        'event_id': document['event_id'], 'schema_version': 1, 'type': event_type,
        'tenant_id': document['tenant_id'], 'business_unit_id': document['business_unit_id'],
        'campaign_id': document['campaign_id'], 'agent_id': document['agent_id'],
        'operation_id': document['call_id'], 'correlation_id': document['correlation_id'],
        'occurred_at': document['timestamp'], 'sequence': document['sequence'],
        'odoo_user_id': document.get('user_id') or document['agent_id'],
    }
    subject = f"telephony.agent.{value['tenant_id']}.{value['campaign_id']}.{value['agent_id']}"
    return subject, {'event': value}
