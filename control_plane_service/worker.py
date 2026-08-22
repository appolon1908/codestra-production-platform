from __future__ import annotations

import json
import hashlib
import hmac
import os
import time
import urllib.request
import urllib.parse

from .core import Store
from .providers import submit

MAX_ATTEMPTS = int(os.getenv("CONTROL_PLANE_MAX_ATTEMPTS", "5"))


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


def once() -> int:
    if os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true":
        return 0
    current = store()
    with current.connect() as db:
        rows = db.execute("SELECT e.*,d.target,d.attempts delivery_attempts FROM events e JOIN event_deliveries d ON d.event_id=e.event_id WHERE d.state IN ('queued','retrying') AND d.next_attempt<=? ORDER BY e.created_at LIMIT 50", (time.time(),)).fetchall()
    processed = 0
    for row in rows:
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
        if target_name == "odoo":
            with current.connect() as db:
                n8n_state = db.execute("SELECT state FROM event_deliveries WHERE event_id=? AND target='n8n'", (row["event_id"],)).fetchone()
            if n8n_state and n8n_state["state"] != "delivered":
                continue
        target = os.getenv("CONTROL_PLANE_" + target_name.upper() + "_URL", "")
        if target_name == "odoo" and str(envelope.get("event_type")) in {"klyrow.email.delivered", "klyrow.email.bounced", "klyrow.email.deferred"}:
            target = os.getenv("CONTROL_PLANE_ODOO_EMAIL_STATUS_URL", target)
        event_slug = {"kyqra.record.created": "crawler-result-created", "kyqra.job.completed": "crawler-job-completed", "kyqra.job.failed": "crawler-job-failed"}.get(str(envelope.get("event_type")))
        if not event_slug: event_slug = str(envelope.get("event_type", "")).removeprefix("telnexa.").removeprefix("klyrow.").replace(".", "-")
        target = target.replace("{event_type}", event_slug)
        if not target: continue
        if not current.circuit_allows(target_name, int(os.getenv("CONTROL_PLANE_CIRCUIT_COOLDOWN", "30"))):
            attempts = row["delivery_attempts"] + 1; state = "dead_letter" if attempts >= MAX_ATTEMPTS else "retrying"; delay = min(300, 2 ** attempts)
            with current.connect() as db:
                db.execute("UPDATE event_deliveries SET state=?,attempts=?,next_attempt=?,last_error=? WHERE event_id=? AND target=?",(state,attempts,time.time()+delay,"CircuitOpen",row["event_id"],target_name))
                db.execute("UPDATE events SET state=?,attempts=CASE WHEN attempts>? THEN attempts ELSE ? END,next_attempt=?,last_error=? WHERE event_id=?",(state,attempts,attempts,time.time()+delay,"CircuitOpen",row["event_id"]))
            processed += 1
            continue
        try:
            req = delivery_request(target_name, target, delivery_row)
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status >= 300: raise RuntimeError("downstream_status")
            with current.connect() as db:
                db.execute("UPDATE event_deliveries SET state='delivered',last_error=NULL WHERE event_id=? AND target=?", (row["event_id"],target_name))
                count_row=db.execute("SELECT count(*) AS n FROM event_deliveries WHERE event_id=? AND state!='delivered'",(row["event_id"],)).fetchone(); pending=count_row["n"]
                if pending==0: db.execute("UPDATE events SET state='delivered',last_error=NULL WHERE event_id=?",(row["event_id"],))
            current.circuit_result(target_name, True)
        except Exception as exc:
            current.circuit_result(target_name, False, int(os.getenv("CONTROL_PLANE_CIRCUIT_THRESHOLD", "3")))
            attempts = row["delivery_attempts"] + 1; state = "dead_letter" if attempts >= MAX_ATTEMPTS else "retrying"; delay = min(300, 2 ** attempts)
            with current.connect() as db:
                db.execute("UPDATE event_deliveries SET state=?,attempts=?,next_attempt=?,last_error=? WHERE event_id=? AND target=?",(state,attempts,time.time()+delay,type(exc).__name__,row["event_id"],target_name))
                db.execute("UPDATE events SET state=?,attempts=CASE WHEN attempts>? THEN attempts ELSE ? END,next_attempt=?,last_error=? WHERE event_id=?",(state,attempts,attempts,time.time()+delay,type(exc).__name__,row["event_id"]))
        processed += 1
    return processed


def dispatch_messages() -> int:
    if os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true":
        return 0
    current = store(); processed = 0
    with current.connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM messages WHERE status='queued' ORDER BY created_at LIMIT 50")]
    for message in rows:
        if not current.circuit_allows(message["provider"], int(os.getenv("CONTROL_PLANE_CIRCUIT_COOLDOWN", "30"))):
            continue
        try:
            result = submit(message)
            current.transition_message(message["message_id"], message["tenant_id"], result.status, result.raw_status, provider_message_id=result.provider_message_id)
            current.circuit_result(message["provider"], True)
        except Exception as exc:
            current.circuit_result(message["provider"], False, int(os.getenv("CONTROL_PLANE_CIRCUIT_THRESHOLD", "3")))
            with current.connect() as db:
                row=db.execute("SELECT retry_count FROM messages WHERE message_id=?",(message["message_id"],)).fetchone(); attempts=row["retry_count"]+1
                db.execute("UPDATE messages SET status=?,retry_count=?,provider_error_code=? WHERE message_id=?",("failed" if attempts>=MAX_ATTEMPTS else "queued",attempts,type(exc).__name__,message["message_id"]))
        processed += 1
    return processed


def main() -> None:
    while True:
        once(); dispatch_messages(); time.sleep(1)


if __name__ == "__main__":
    main()
