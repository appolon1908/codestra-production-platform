"""Runtime adapter for the isolated TEL-EVENTS publisher.

The service is intentionally inert unless both `TEL_EVENTS_ENABLED=true` and
`SEND_EVENTS=true` are explicitly set and the external-delivery kill switch is
absent.  It has no provisioning or telephony-origination code path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pymysql

from .publisher import DeliveryLedger, PublisherError, build_call_ended_event, load_watermark, wire_event


def _secret(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        value = handle.read().strip()
    if not value:
        raise PublisherError("required secret is empty")
    return value


def _enabled() -> bool:
    return (
        os.getenv("TEL_EVENTS_ENABLED", "false").lower() in ("1", "true", "yes")
        and os.getenv("SEND_EVENTS", "false").lower() in ("1", "true", "yes")
        and not os.path.exists(os.getenv("DELIVERY_KILL_SWITCH", "/etc/codestra/disable-external-delivery"))
    )


def _body(event: dict) -> bytes:
    return json.dumps(wire_event(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _post(event: dict) -> int:
    body = _body(event)
    timestamp = str(int(time.time()))
    secret = _secret(os.environ["TEL_EVENTS_HMAC_FILE"])
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        os.environ["TEL_EVENTS_ENDPOINT"],
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": event["idempotency_key"],
            "X-Signature": signature,
            "X-Timestamp": timestamp,
            "X-Client-Instance-ID": os.environ["TEL_EVENTS_CLIENT_INSTANCE"],
        },
    )
    context = ssl.create_default_context(cafile=os.environ["TEL_EVENTS_CA_FILE"])
    context.load_cert_chain(os.environ["TEL_EVENTS_CERT_FILE"], os.environ["TEL_EVENTS_KEY_FILE"])
    try:
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def _db():
    return pymysql.connect(
        host=os.environ.get("VICIDIAL_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("VICIDIAL_DB_PORT", "3306")),
        user=os.environ["VICIDIAL_DB_USER"],
        password=_secret(os.environ["VICIDIAL_DB_PASS_FILE"]),
        database=os.environ.get("VICIDIAL_DB_NAME", "asterisk"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _rows(db, table: str, end_epoch: int, source_id: str, limit: int = 100):
    if table == "vicidial_log":
        source = "uniqueid"
    elif table == "vicidial_closer_log":
        source = "closecallid"
    else:
        raise PublisherError("unapproved source table")
    sql = f"""SELECT {source},end_epoch,length_in_sec,status,campaign_id,user_group
              FROM {table}
              WHERE end_epoch > %s AND status IS NOT NULL AND status <> ''
                AND (end_epoch > %s OR (end_epoch = %s AND {source} > %s))
              ORDER BY end_epoch,{source} LIMIT %s"""
    with db.cursor() as cursor:
        cursor.execute(sql, (end_epoch, end_epoch, end_epoch, source_id, limit))
        return cursor.fetchall()


def run_once() -> int:
    if not _enabled():
        return 0
    boundaries = load_watermark(os.environ["TEL_EVENTS_WATERMARK"], allowed_group="codestra-events")
    ledger = DeliveryLedger(os.environ["TEL_EVENTS_LEDGER"])
    db = _db()
    sent = 0
    try:
        for boundary in boundaries:
            cursor = ledger.cursor(boundary.table, boundary.high_water)
            if cursor.end_epoch < boundary.boundary_epoch:
                cutoff_epoch, cutoff_id = boundary.boundary_epoch, ""
            else:
                cutoff_epoch, cutoff_id = cursor.end_epoch, cursor.source_id
            rows = _rows(db, boundary.table, cutoff_epoch, cutoff_id)
            for row in rows:
                event = build_call_ended_event(row, boundary.table)
                ledger.stage(event)
                if ledger.state(event["event_id"]) == "acknowledged":
                    continue
                for _ in range(3):
                    status = _post(event)
                    result = ledger.acknowledge(event["event_id"], status)
                    if result == "acknowledged":
                        sent += 1
                        break
                    if result == "dead_letter":
                        raise PublisherError("delivery entered dead-letter state")
                    time.sleep(1)
        return sent
    finally:
        db.close()
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(run_once())
