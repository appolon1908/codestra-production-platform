from __future__ import annotations

import json
import hashlib
import hmac
import os
import random
import re
import time
import urllib.request
import asyncio
import urllib.parse
from pathlib import Path
import nats

from .core import Store
from .providers import submit
from .leasing import (
    WORKER_ID,
    claim_event_deliveries,
    claim_messages,
    renew_event_lease,
    renew_message_lease,
)

MAX_ATTEMPTS = int(os.getenv("CONTROL_PLANE_MAX_ATTEMPTS", "5"))
HTTP_TIMEOUT = int(os.getenv("CONTROL_PLANE_HTTP_TIMEOUT", "10"))
WORKER_HEARTBEAT_FILE = Path(
    os.getenv("CONTROL_PLANE_WORKER_HEARTBEAT_FILE", "/tmp/control-plane-worker-heartbeat")
)


def delivery_request(target_name: str, target: str, row: object) -> urllib.request.Request:
    raw = str(row["envelope"]).encode()
    correlation = str(row["correlation_id"]); event_id = str(row["event_id"]); stamp = str(int(time.time()))
    headers = {"Content-Type": "application/json", "X-Correlation-Id": correlation, "X-Event-Id": event_id, "X-Timestamp": stamp, "Idempotency-Key": event_id}
    if target_name == "odoo":
        secret = os.getenv("ODOO_OUTBOUND_HMAC_SECRET", "")
        if not secret: raise RuntimeError("odoo_outbound_secret_missing")
        path = urllib.parse.urlsplit(target).path
        canonical = b"\n".join((stamp.encode(), event_id.encode(), b"POST", path.encode(), raw)) if path.endswith("/email-events") else stamp.encode() + b"." + raw
        signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        headers.update({"X-Codestra-Timestamp": stamp, "X-Codestra-Event-ID": event_id, "X-Codestra-Signature": signature, "X-Tenant-ID": str(row["tenant_id"])})
    elif target_name == "n8n":
        token = os.getenv("N8N_OUTBOUND_API_KEY", ""); secret = os.getenv("N8N_MIDDLEWARE_HMAC_SECRET", "")
        if not token or not secret: raise RuntimeError("n8n_outbound_credentials_missing")
        signature = hmac.new(secret.encode(), b"\n".join((stamp.encode(), event_id.encode(), b"middleware", raw)), hashlib.sha256).hexdigest()
        headers.update({"Authorization": "Bearer " + token, "X-Event-Source": "middleware", "X-Signature": "sha256=" + signature})
    return urllib.request.Request(target, raw, headers, method="POST")


def store() -> Store:
    return Store(os.getenv("CONTROL_PLANE_DB", "/data/control-plane.db"))


def retry_delay(attempts: int) -> float:
    base = min(300.0, float(2 ** attempts))
    return base + random.uniform(0.0, min(30.0, base * 0.25))


async def _publish_calling_event(envelope: dict) -> None:
    credentials = os.getenv("REALTIME_NATS_PUBLISH_CREDENTIALS_FILE", "")
    digest = os.getenv("CALLING_CONTRACT_DIGEST", "")
    payload = envelope.get("payload") or {}
    required = {"event_id", "schema_version", "type", "tenant_id", "business_unit_id", "campaign_id",
                "agent_id", "operation_id", "correlation_id", "occurred_at", "sequence"}
    allowed_types = {
        "telephony.call.ringing.v1", "telephony.call.answered.v1",
        "telephony.call.connected.v1", "telephony.call.transferred.v1",
        "telephony.call.completed.v1", "telephony.call.missed.v1",
        "telephony.call.dispositioned.v1", "telephony.agent.status-changed.v1",
    }
    if (not credentials or not re.fullmatch(r"[0-9a-f]{64}", digest) or not isinstance(payload, dict)
            or required - set(payload)):
        raise RuntimeError("calling_publication_contract_missing")
    if (not isinstance(payload["type"], str) or payload["type"] not in allowed_types
            or type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or type(payload["sequence"]) is not int or payload["sequence"] < 1
            or str(payload["event_id"]) != str(envelope.get("event_id"))
            or str(payload["type"]) != str(envelope.get("event_type"))
            or str(payload["tenant_id"]) != str(envelope.get("tenant_id"))
            or str(payload["correlation_id"]) != str(envelope.get("correlation_id"))
            or str(payload["occurred_at"]) != str(envelope.get("occurred_at"))):
        raise RuntimeError("calling_publication_contract_mismatch")
    tokens = [str(payload[key]) for key in ("tenant_id", "campaign_id", "agent_id")]
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", token) for token in tokens):
        raise RuntimeError("calling_publication_subject_rejected")
    subject = "telephony.agent." + ".".join(tokens)
    client = await nats.connect(
        servers=[os.getenv("REALTIME_NATS_URL", "tls://codestra-nats:4222")],
        user_credentials=credentials, connect_timeout=3, max_reconnect_attempts=3,
    )
    try:
        await client.jetstream().publish(
            subject, json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Nats-Msg-Id": str(payload["event_id"]),
                     "Codestra-Contract-Digest": digest},
        )
    finally:
        await client.close()


def release_message_lease(current: Store, message: dict, status: str, *,
                          attempts: int | None = None, error: str | None = None,
                          next_attempt: float = 0) -> bool:
    assignments = ["status=?", "lease_owner=NULL", "lease_token=NULL", "lease_expires_at=NULL",
                   "provider_error_code=?", "next_attempt=?"]
    values: list[object] = [status, error, next_attempt]
    if attempts is not None:
        assignments.append("retry_count=?")
        values.append(attempts)
    values.extend((message["message_id"], WORKER_ID, message["lease_token"]))
    with current.connect() as db:
        changed = db.execute(
            "UPDATE messages SET " + ",".join(assignments)
            + " WHERE message_id=? AND lease_owner=? AND lease_token=?",
            values,
        ).rowcount
    return changed == 1


def once() -> int:
    if os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true":
        return 0
    current = store()
    rows = claim_event_deliveries(current)
    processed = 0
    for row in rows:
        if not renew_event_lease(current, row):
            continue
        envelope = json.loads(row["envelope"])
        if envelope.get("source") == "klyrow" and envelope.get("event_type") == "klyrow.email.event":
            inner_type = str((envelope.get("payload") or {}).get("event_type", ""))
            if inner_type in {"klyrow.email.delivered", "klyrow.email.bounced", "klyrow.email.deferred"}:
                envelope["metadata"] = dict(envelope.get("metadata") or {})
                envelope["metadata"]["transport_event_type"] = envelope["event_type"]
                envelope["event_type"] = inner_type
        delivery_row = dict(row)
        delivery_row["envelope"] = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        target_name = row["target"]
        if target_name == "calling":
            if os.getenv("REALTIME_EVENT_DELIVERY_ENABLED", "false") != "true":
                with current.connect() as db:
                    db.execute("""UPDATE event_deliveries SET state='queued',lease_owner=NULL,
                        lease_token=NULL,lease_expires_at=NULL
                        WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?""",
                        (row["event_id"], target_name, WORKER_ID, row["lease_token"]))
                continue
            try:
                asyncio.run(_publish_calling_event(envelope))
                with current.connect() as db:
                    changed = db.execute("""UPDATE event_deliveries SET state='delivered',last_error=NULL,
                        lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                        WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?""",
                        (row["event_id"], target_name, WORKER_ID, row["lease_token"])).rowcount
                    if changed != 1:
                        raise RuntimeError("delivery_lease_lost")
                    pending = db.execute(
                        "SELECT count(*) AS n FROM event_deliveries WHERE event_id=? AND state!='delivered'",
                        (row["event_id"],),
                    ).fetchone()["n"]
                    if pending == 0:
                        db.execute("UPDATE events SET state='delivered',last_error=NULL WHERE event_id=?",
                                   (row["event_id"],))
                processed += 1
                continue
            except Exception as exc:
                attempts = row["delivery_attempts"] + 1
                state = "dead_letter" if attempts >= MAX_ATTEMPTS else "retrying"
                delay = retry_delay(attempts)
                with current.connect() as db:
                    changed = db.execute("""UPDATE event_deliveries SET state=?,attempts=?,next_attempt=?,last_error=?,
                        lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                        WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?""",
                        (state, attempts, time.time() + delay, type(exc).__name__, row["event_id"],
                         target_name, WORKER_ID, row["lease_token"])).rowcount
                    if changed == 1:
                        db.execute("""UPDATE events SET state=?,
                            attempts=CASE WHEN attempts>? THEN attempts ELSE ? END,
                            next_attempt=?,last_error=? WHERE event_id=?""",
                            (state, attempts, attempts, time.time() + delay,
                             type(exc).__name__, row["event_id"]))
                processed += 1
                continue
        if target_name == "odoo":
            with current.connect() as db:
                n8n_state = db.execute("SELECT state FROM event_deliveries WHERE event_id=? AND target='n8n'", (row["event_id"],)).fetchone()
            if n8n_state and n8n_state["state"] != "delivered":
                with current.connect() as db:
                    db.execute("""UPDATE event_deliveries
                        SET state='queued',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                        WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?""",
                        (row["event_id"], target_name, WORKER_ID, row["lease_token"]))
                continue
        target = os.getenv("CONTROL_PLANE_" + target_name.upper() + "_URL", "")
        if target_name == "odoo" and str(envelope.get("event_type")) in {"klyrow.email.delivered", "klyrow.email.bounced", "klyrow.email.deferred"}:
            target = os.getenv("CONTROL_PLANE_ODOO_EMAIL_STATUS_URL", target)
        event_slug = {"kyqra.record.created": "crawler-result-created", "kyqra.job.completed": "crawler-job-completed", "kyqra.job.failed": "crawler-job-failed"}.get(str(envelope.get("event_type")))
        if not event_slug: event_slug = str(envelope.get("event_type", "")).removeprefix("telnexa.").removeprefix("klyrow.").replace(".", "-")
        target = target.replace("{event_type}", event_slug)
        if not target:
            attempts = row["delivery_attempts"] + 1
            state = "dead_letter" if attempts >= MAX_ATTEMPTS else "retrying"
            delay = retry_delay(attempts)
            with current.connect() as db:
                changed = db.execute(
                    """UPDATE event_deliveries SET state=?,attempts=?,next_attempt=?,last_error=?,
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                    WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?""",
                    (state, attempts, time.time() + delay,
                     "TargetNotConfigured", row["event_id"], target_name,
                     WORKER_ID, row["lease_token"]),
                ).rowcount
                if changed == 1:
                    db.execute(
                        """UPDATE events SET state=?,attempts=CASE WHEN attempts>? THEN attempts ELSE ? END,
                           next_attempt=?,last_error=? WHERE event_id=?""",
                        (state, attempts, attempts, time.time() + delay,
                         "TargetNotConfigured", row["event_id"]),
                    )
            processed += 1
            continue
        if not current.circuit_allows(target_name, int(os.getenv("CONTROL_PLANE_CIRCUIT_COOLDOWN", "30"))):
            attempts = row["delivery_attempts"] + 1; state = "dead_letter" if attempts >= MAX_ATTEMPTS else "retrying"; delay = retry_delay(attempts)
            with current.connect() as db:
                changed = db.execute("""UPDATE event_deliveries SET state=?,attempts=?,next_attempt=?,last_error=?,
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                    WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?""",
                    (state,attempts,time.time()+delay,"CircuitOpen",row["event_id"],target_name,WORKER_ID,row["lease_token"])).rowcount
                if changed == 1:
                    db.execute("UPDATE events SET state=?,attempts=CASE WHEN attempts>? THEN attempts ELSE ? END,next_attempt=?,last_error=? WHERE event_id=?",(state,attempts,attempts,time.time()+delay,"CircuitOpen",row["event_id"]))
            processed += 1
            continue
        try:
            req = delivery_request(target_name, target, delivery_row)
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                if response.status >= 300: raise RuntimeError("downstream_status")
            with current.connect() as db:
                changed = db.execute("""UPDATE event_deliveries SET state='delivered',last_error=NULL,
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                    WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?""",
                    (row["event_id"],target_name,WORKER_ID,row["lease_token"])).rowcount
                if changed != 1:
                    raise RuntimeError("delivery_lease_lost")
                count_row=db.execute("SELECT count(*) AS n FROM event_deliveries WHERE event_id=? AND state!='delivered'",(row["event_id"],)).fetchone(); pending=count_row["n"]
                if pending==0: db.execute("UPDATE events SET state='delivered',last_error=NULL WHERE event_id=?",(row["event_id"],))
            current.circuit_result(target_name, True)
        except Exception as exc:
            current.circuit_result(target_name, False, int(os.getenv("CONTROL_PLANE_CIRCUIT_THRESHOLD", "3")))
            attempts = row["delivery_attempts"] + 1; state = "dead_letter" if attempts >= MAX_ATTEMPTS else "retrying"; delay = retry_delay(attempts)
            with current.connect() as db:
                changed = db.execute("""UPDATE event_deliveries SET state=?,attempts=?,next_attempt=?,last_error=?,
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                    WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?""",
                    (state,attempts,time.time()+delay,type(exc).__name__,row["event_id"],target_name,WORKER_ID,row["lease_token"])).rowcount
                if changed == 1:
                    db.execute("UPDATE events SET state=?,attempts=CASE WHEN attempts>? THEN attempts ELSE ? END,next_attempt=?,last_error=? WHERE event_id=?",(state,attempts,attempts,time.time()+delay,type(exc).__name__,row["event_id"]))
        processed += 1
    return processed


def dispatch_messages() -> int:
    if os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true":
        return 0
    current = store(); processed = 0
    rows = claim_messages(current)
    for message in rows:
        if not current.circuit_allows(message["provider"], int(os.getenv("CONTROL_PLANE_CIRCUIT_COOLDOWN", "30"))):
            release_message_lease(
                current, message, "queued", error="CircuitOpen",
                next_attempt=time.time() + retry_delay(int(message["retry_count"]) + 1),
            )
            continue
        try:
            if not renew_message_lease(current, message):
                continue
            if (message["classification"] == "marketing"
                    and not current.preference_allows(
                        message["tenant_id"], message["customer_id"], message["channel"]
                    )):
                if not current.transition_leased_message(
                    message["message_id"], message["tenant_id"], WORKER_ID,
                    message["lease_token"], "blocked", "consent_revoked",
                    error_code="consent_revoked",
                ):
                    raise RuntimeError("message_lease_lost")
                processed += 1
                continue
            if current.is_suppressed(
                message["tenant_id"], message["channel"], message["normalized_destination"]
            ):
                if not current.transition_leased_message(
                    message["message_id"], message["tenant_id"], WORKER_ID,
                    message["lease_token"], "blocked", "destination_suppressed",
                    error_code="destination_suppressed",
                ):
                    raise RuntimeError("message_lease_lost")
                processed += 1
                continue
            result = submit(message)
            if not current.transition_leased_message(
                message["message_id"], message["tenant_id"], WORKER_ID,
                message["lease_token"], result.status, result.raw_status,
                provider_message_id=result.provider_message_id,
            ):
                raise RuntimeError("message_lease_lost")
            current.circuit_result(message["provider"], True)
        except Exception as exc:
            current.circuit_result(message["provider"], False, int(os.getenv("CONTROL_PLANE_CIRCUIT_THRESHOLD", "3")))
            attempts = int(message["retry_count"]) + 1
            final = attempts >= MAX_ATTEMPTS
            release_message_lease(
                current, message, "failed" if final else "queued", attempts=attempts,
                error=type(exc).__name__, next_attempt=0 if final else time.time() + retry_delay(attempts),
            )
        processed += 1
    return processed


def main() -> None:
    while True:
        once()
        dispatch_messages()
        WORKER_HEARTBEAT_FILE.write_text(str(time.time()), encoding="ascii")
        time.sleep(1)


if __name__ == "__main__":
    main()
