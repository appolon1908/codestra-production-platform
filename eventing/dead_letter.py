"""Application-side forwarding for JetStream maximum-delivery advisories."""

from __future__ import annotations

import json


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
    headers = {
        "Nats-Msg-Id": f"dead-letter:{stream}:{consumer}:{event_id}",
        "Codestra-Original-Stream": stream,
        "Codestra-Original-Consumer": consumer,
        "Codestra-Failure-Class": "max_deliver_exhausted",
    }
    acknowledgement = await js.publish(dead_letter_subject, original.data, headers=headers)
    return "duplicate" if acknowledgement.duplicate else "forwarded"
