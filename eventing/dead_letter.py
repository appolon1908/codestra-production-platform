"""Application-side forwarding for JetStream maximum-delivery advisories."""

from __future__ import annotations

import json
from datetime import datetime, timezone


class DeadLetterError(RuntimeError):
    pass


async def forward_max_delivery_advisory(js, advisory_payload: bytes) -> str:
    """Persist the exhausted original message in the tenant/campaign DLQ.

    JetStream advisories do not move messages themselves. This handler reads the
    original message by stream sequence and republishes it with a stable message
    ID, making repeated advisories effective-once through stream deduplication.
    """
    try:
        advisory = json.loads(advisory_payload)
        stream = advisory["stream"]
        consumer = advisory["consumer"]
        sequence = int(advisory["stream_seq"])
        deliveries = int(advisory["deliveries"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeadLetterError("invalid maximum-delivery advisory") from exc
    original = await js.get_msg(stream, seq=sequence)
    segments = original.subject.split(".")
    if len(segments) != 6 or segments[:2] != ["codestra", "v1"] or segments[4] != "events":
        raise DeadLetterError("original subject is outside the Codestra event contract")
    dead_letter_subject = ".".join([*segments[:5], "dead_letter"])
    envelope = json.loads(original.data)
    event_id = envelope.get("event_id")
    if not event_id:
        raise DeadLetterError("original event identity is missing")
    envelope["failure"] = {
        "failure_class": "max_deliver_exhausted",
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "delivery_attempts": deliveries,
    }
    dead_letter_data = json.dumps(
        envelope, sort_keys=True, separators=(",", ":")
    ).encode()
    headers = {
        "Nats-Msg-Id": f"dead-letter:{stream}:{consumer}:{event_id}",
        "Codestra-Original-Stream": stream,
        "Codestra-Original-Consumer": consumer,
        "Codestra-Failure-Class": "max_deliver_exhausted",
    }
    acknowledgement = await js.publish(dead_letter_subject, dead_letter_data, headers=headers)
    return "duplicate" if acknowledgement.duplicate else "forwarded"


async def bind_dead_letter_advisory_consumer(js):
    """Bind the preprovisioned durable consumer exactly once per worker."""
    return await js.pull_subscribe_bind(
        durable="middleware-dlq-advisory-v1",
        stream="CODESTRA_DLQ_ADVISORIES_V1",
    )


async def process_next_dead_letter_advisory(
    js, subscription, timeout: float = 1.0
) -> str:
    """Forward and acknowledge one durably captured advisory."""
    message = (await subscription.fetch(1, timeout=timeout))[0]
    try:
        result = await forward_max_delivery_advisory(js, message.data)
    except Exception:
        await message.nak()
        raise
    await message.ack()
    return result
