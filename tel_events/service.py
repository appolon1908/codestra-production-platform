"""Runtime adapter for the isolated TEL-EVENTS publisher.

The service is fail-closed unless its enable flags, approved runtime mode,
bounded delivery budget, explicit campaign/user-group allowlists, and external
kill switch all permit delivery. It has no provisioning, call-origination, or
telephony-control code path.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import pymysql

from .publisher import (
    DeliveryLedger,
    PublisherError,
    build_call_ended_event,
    load_watermark,
    wire_event,
)


@dataclass(frozen=True)
class RuntimePolicy:
    mode: str
    event_budget: int
    campaigns: frozenset[str]
    user_groups: frozenset[str]


def _secret(path: str) -> str:
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o027:
        raise PublisherError("secret must be a regular, non-writable private file")
    with open(path, encoding="utf-8") as handle:
        value = handle.read().strip()
    if not value:
        raise PublisherError("required secret is empty")
    return value


def _enabled() -> bool:
    return (
        os.getenv("TEL_EVENTS_ENABLED", "false").lower() in ("1", "true", "yes")
        and os.getenv("SEND_EVENTS", "false").lower() in ("1", "true", "yes")
        and not os.path.exists(
            os.getenv("DELIVERY_KILL_SWITCH", "/etc/codestra/disable-external-delivery")
        )
    )


def _allowlist(name: str) -> frozenset[str]:
    values = frozenset(
        value.strip() for value in os.getenv(name, "").split(",") if value.strip()
    )
    if not values:
        raise PublisherError(f"{name} must contain an explicit approved allowlist")
    return values


def _runtime_policy() -> RuntimePolicy:
    mode = os.getenv("TEL_EVENTS_MODE", "disabled").strip().lower()
    if mode not in ("canary", "production"):
        raise PublisherError("TEL_EVENTS_MODE must be canary or production")
    try:
        budget = int(os.environ["TEL_EVENTS_EVENT_BUDGET"])
    except (KeyError, ValueError) as exc:
        raise PublisherError("TEL_EVENTS_EVENT_BUDGET must be an integer") from exc
    if mode == "canary" and not 5 <= budget <= 10:
        raise PublisherError("canary budget must be between 5 and 10 finalized events")
    if mode == "production" and not 1 <= budget <= 100:
        raise PublisherError("production iteration budget must be between 1 and 100")
    return RuntimePolicy(
        mode=mode,
        event_budget=budget,
        campaigns=_allowlist("TEL_EVENTS_CAMPAIGN_ALLOWLIST"),
        user_groups=_allowlist("TEL_EVENTS_USER_GROUP_ALLOWLIST"),
    )


def _body(event: dict) -> bytes:
    return json.dumps(
        wire_event(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _signature_input(
    method: str, path: str, timestamp: str, event_id: str, body: bytes
) -> bytes:
    normalized_path = "/" + "/".join(part for part in path.split("/") if part)
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join(
        ("v1", method.upper(), normalized_path, timestamp, event_id, body_hash)
    ).encode()


def _post(event: dict) -> int:
    body = _body(event)
    timestamp = str(int(time.time()))
    secret = _secret(os.environ["TEL_EVENTS_HMAC_FILE"])
    endpoint = urllib.parse.urlsplit(os.environ["TEL_EVENTS_ENDPOINT"])
    signature = hmac.new(
        secret.encode(),
        _signature_input("POST", endpoint.path, timestamp, event["event_id"], body),
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        os.environ["TEL_EVENTS_ENDPOINT"],
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": event["idempotency_key"],
            "X-Signature": signature,
            "X-Signature-Version": "v1",
            "X-Timestamp": timestamp,
            "X-Event-ID": event["event_id"],
            "X-Client-Instance-ID": os.environ["TEL_EVENTS_CLIENT_INSTANCE"],
        },
    )
    context = ssl.create_default_context(cafile=os.environ["TEL_EVENTS_CA_FILE"])
    context.load_cert_chain(
        os.environ["TEL_EVENTS_CERT_FILE"], os.environ["TEL_EVENTS_KEY_FILE"]
    )
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


def _rows(
    db,
    table: str,
    boundary_epoch: int,
    cursor_end_epoch: int,
    source_id: str,
    campaigns: frozenset[str],
    user_groups: frozenset[str],
    limit: int = 100,
):
    if not 1 <= limit <= 100:
        raise PublisherError("batch limit must be between 1 and 100")
    if table == "vicidial_log":
        source = "uniqueid"
    elif table == "vicidial_closer_log":
        source = "closecallid"
    else:
        raise PublisherError("unapproved source table")
    campaign_slots = ",".join("%s" for _ in campaigns)
    group_slots = ",".join("%s" for _ in user_groups)
    sql = f"""SELECT {source},end_epoch,length_in_sec,status,campaign_id,user_group
              FROM {table}
              WHERE end_epoch > %s AND status IS NOT NULL AND status <> ''
                AND (end_epoch > %s OR (end_epoch = %s AND {source} > %s))
                AND campaign_id IN ({campaign_slots})
                AND user_group IN ({group_slots})
              ORDER BY end_epoch,{source} LIMIT %s"""
    with db.cursor() as cursor:
        cursor.execute(
            sql,
            (
                boundary_epoch,
                cursor_end_epoch,
                cursor_end_epoch,
                source_id,
                *sorted(campaigns),
                *sorted(user_groups),
                limit,
            ),
        )
        return cursor.fetchall()


def _in_scope(event: dict, policy: RuntimePolicy) -> bool:
    payload = event["payload"]
    campaign = payload.get("campaign_reference")
    user_group = payload.get("business_unit_reference")
    return campaign in policy.campaigns and user_group in policy.user_groups


def _round_robin(rows_by_source, start_index: int = 0):
    """Yield one row per source in turn so neither VICIdial log can starve."""
    offsets = [0] * len(rows_by_source)
    while True:
        yielded = False
        for offset in range(len(rows_by_source)):
            index = (start_index + offset) % len(rows_by_source)
            boundary, rows = rows_by_source[index]
            if offsets[index] < len(rows):
                row = rows[offsets[index]]
                offsets[index] += 1
                yielded = True
                yield boundary, row
        if not yielded:
            return


def run_once() -> int:
    if not _enabled():
        return 0
    policy = _runtime_policy()
    boundaries = load_watermark(
        os.environ["TEL_EVENTS_WATERMARK"], allowed_group="codestra-events"
    )
    ledger = DeliveryLedger(os.environ["TEL_EVENTS_LEDGER"])
    db = _db()
    sent = 0
    try:
        if policy.mode == "canary":
            remaining = policy.event_budget - ledger.acknowledged_count()
            if remaining <= 0:
                return 0
        else:
            remaining = policy.event_budget

        rows_by_source = []
        for boundary in boundaries:
            cursor = ledger.cursor(boundary.table, boundary.high_water)
            if cursor < boundary.high_water:
                raise PublisherError(
                    "publisher cursor regressed behind the approved watermark"
                )
            rows = _rows(
                db,
                boundary.table,
                boundary.boundary_epoch,
                cursor.end_epoch,
                cursor.source_id,
                policy.campaigns,
                policy.user_groups,
                min(100, max(remaining, 1)),
            )
            rows_by_source.append((boundary, rows))
        start_index = ledger.claim_source_start(len(rows_by_source))
        for boundary, row in _round_robin(rows_by_source, start_index):
            if remaining <= 0:
                break
            event = build_call_ended_event(row, boundary.table)
            if not _in_scope(event, policy):
                ledger.skip(event, "outside approved campaign or user-group scope")
                continue
            ledger.stage(event)
            state = ledger.state(event["event_id"])
            if state == "acknowledged":
                continue
            if state == "dead_letter":
                raise PublisherError(
                    "dead-lettered event requires operator reconciliation"
                )
            for _ in range(3):
                if not _enabled():
                    raise PublisherError(
                        "publisher was disabled or its kill switch was installed"
                    )
                try:
                    status = _post(event)
                except (OSError, urllib.error.URLError) as exc:
                    result = ledger.fail(
                        event["event_id"],
                        f"delivery transport failed: {type(exc).__name__}",
                    )
                else:
                    result = ledger.acknowledge(event["event_id"], status)
                if result == "acknowledged":
                    sent += 1
                    remaining -= 1
                    break
                if result == "dead_letter":
                    raise PublisherError("delivery entered dead-letter state")
                time.sleep(1)
        return sent
    finally:
        db.close()
        ledger.close()


def run_forever() -> None:
    policy = _runtime_policy()
    if policy.mode != "production":
        raise PublisherError("persistent loop is allowed only in production mode")
    interval = int(os.getenv("TEL_EVENTS_INTERVAL_SECONDS", "15"))
    if not 5 <= interval <= 300:
        raise PublisherError("TEL_EVENTS_INTERVAL_SECONDS must be between 5 and 300")
    while True:
        if not _enabled():
            raise PublisherError(
                "publisher was disabled or its kill switch was installed"
            )
        run_once()
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    if args.loop:
        run_forever()
    else:
        sent = run_once()
        print(f"TEL_EVENTS_SENT={sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
