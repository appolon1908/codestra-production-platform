"""Fail-closed, identity-independent finalized call-ended publisher core.

This module deliberately has no VICIdial provisioning, Odoo, Keycloak, PJSIP,
extension, or telephony-origination dependency.  Database and HTTP adapters
belong to the separately deployed TEL-EVENTS service.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


EVENT_TYPE = "vicidial.call.ended"
SOURCES = ("vicidial_log", "vicidial_closer_log")
TRANSIENT_ACKS = frozenset((408, 425, 429, 500, 502, 503, 504))
SUCCESS_ACKS = frozenset((200, 201, 202, 204))
MAX_DURATION_SECONDS = 86400
PAYLOAD_FIELDS = frozenset(
    (
        "call_id",
        "ended_at",
        "duration_seconds",
        "direction",
        "disposition_code",
        "campaign_reference",
        "business_unit_reference",
    )
)


class PublisherError(ValueError):
    """A source, watermark, event, or delivery invariant failed."""


@dataclass(frozen=True, order=True)
class Cursor:
    end_epoch: int
    source_id: str

    def __post_init__(self) -> None:
        if isinstance(self.end_epoch, bool) or self.end_epoch < 0:
            raise PublisherError("cursor epoch must be a non-negative integer")
        if not self.source_id:
            raise PublisherError("cursor source id is required")


@dataclass(frozen=True)
class SourceBoundary:
    table: str
    boundary_epoch: int
    high_water: Cursor

    def __post_init__(self) -> None:
        if self.table not in SOURCES:
            raise PublisherError("unapproved source table")
        if self.boundary_epoch < 0:
            raise PublisherError("boundary epoch is invalid")


def _utc_epoch(value: str) -> int:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PublisherError("captured_at must be UTC RFC3339")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise PublisherError("captured_at is invalid") from exc
    return int(parsed.replace(tzinfo=timezone.utc).timestamp())


def load_watermark(
    path: str,
    allowed_group: str | None = None,
    allowed_owner_uid: int = 0,
) -> tuple[SourceBoundary, ...]:
    st = os.lstat(path)
    mode = stat.S_IMODE(st.st_mode)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != allowed_owner_uid:
        raise PublisherError("watermark must be a root-owned regular file")
    if mode not in (0o600, 0o640):
        raise PublisherError(
            "watermark mode must be exactly 0600 or approved-group 0640"
        )
    if mode == 0o640:
        import grp

        if not allowed_group or grp.getgrgid(st.st_gid).gr_name != allowed_group:
            raise PublisherError("watermark group ownership is invalid")
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if value.get("ordering") != ["end_epoch", "stable_source_id"]:
        raise PublisherError("watermark ordering is invalid")
    captured = _utc_epoch(value.get("captured_at", ""))
    sources = value.get("sources")
    if set(sources or {}) != set(SOURCES):
        raise PublisherError("watermark source set is incomplete")
    result = []
    for table in SOURCES:
        row = sources[table]
        try:
            cursor = Cursor(int(row["end_epoch"]), str(row["source_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PublisherError("watermark cursor is invalid") from exc
        result.append(SourceBoundary(table, captured, cursor))
    return tuple(result)


def _source_id(row: Mapping[str, Any], table: str) -> str:
    key = "closecallid" if table == "vicidial_closer_log" else "uniqueid"
    value = row.get(key)
    if value is None or str(value) == "":
        raise PublisherError("finalized row has no stable source id")
    return str(value)


def _ended_epoch(row: Mapping[str, Any]) -> int:
    value = row.get("end_epoch")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PublisherError("finalized row has invalid end_epoch")
    return value


def _event_id(table: str, source_id: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"codestra:{EVENT_TYPE}:{table}:{source_id}")
    )


def build_call_ended_event(row: Mapping[str, Any], table: str) -> dict[str, Any]:
    """Map only the least-data finalized projection into the canonical event."""
    if table not in SOURCES:
        raise PublisherError("unapproved source table")
    source_id = _source_id(row, table)
    ended_epoch = _ended_epoch(row)
    duration = row.get("length_in_sec")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int)
        or not 0 <= duration <= MAX_DURATION_SECONDS
    ):
        raise PublisherError("duration is invalid")
    disposition = row.get("status")
    if not isinstance(disposition, str) or not disposition:
        raise PublisherError("finalized status is required")
    direction = "inbound" if table == "vicidial_closer_log" else "outbound"
    call_id = hashlib.sha256(f"{table}:{source_id}".encode()).hexdigest()
    payload = {
        "call_id": call_id,
        "ended_at": datetime.fromtimestamp(ended_epoch, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "duration_seconds": duration,
        "direction": direction,
        "disposition_code": disposition,
    }
    if row.get("campaign_id") is not None:
        payload["campaign_reference"] = str(row["campaign_id"])
    if row.get("user_group") is not None:
        payload["business_unit_reference"] = str(row["user_group"])
    if set(payload) - PAYLOAD_FIELDS:
        raise PublisherError("payload contains an unsupported field")
    event_id = _event_id(table, source_id)
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "event_type": EVENT_TYPE,
        "occurred_at": payload["ended_at"],
        "correlation_id": f"vicidial:{call_id}",
        "test_syn": False,
        "payload": payload,
        "idempotency_key": f"vicidial:{event_id}",
        "_cursor": {"end_epoch": ended_epoch, "source_id": source_id, "table": table},
    }


def wire_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Remove local cursor/idempotency bookkeeping before serialization."""
    value = dict(event)
    value.pop("_cursor", None)
    value.pop("idempotency_key", None)
    return value


def select_finalized_rows(
    rows: Iterable[Mapping[str, Any]], boundary: SourceBoundary, limit: int = 100
) -> list[Mapping[str, Any]]:
    if not 1 <= limit <= 100:
        raise PublisherError("batch limit must be between 1 and 100")
    selected = []
    for row in rows:
        if not row.get("status"):
            continue
        candidate = Cursor(_ended_epoch(row), _source_id(row, boundary.table))
        if (
            candidate.end_epoch <= boundary.boundary_epoch
            or candidate <= boundary.high_water
        ):
            continue
        selected.append((candidate, row))
    selected.sort(key=lambda pair: pair[0])
    return [row for _, row in selected[:limit]]


class DeliveryLedger:
    """Durable local acknowledgement/retry/dead-letter ledger."""

    def __init__(self, path: str, max_attempts: int = 3) -> None:
        if not 1 <= max_attempts <= 5:
            raise PublisherError("retry budget must be between 1 and 5")
        self.max_attempts = max_attempts
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS event_delivery (
                event_id TEXT PRIMARY KEY, event_json TEXT NOT NULL,
                table_name TEXT NOT NULL, end_epoch INTEGER NOT NULL,
                source_id TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'pending', last_error TEXT,
                acknowledged_at TEXT
            );
            CREATE TABLE IF NOT EXISTS publisher_cursor (
                table_name TEXT PRIMARY KEY, end_epoch INTEGER NOT NULL,
                source_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS skipped_source_row (
                table_name TEXT NOT NULL, end_epoch INTEGER NOT NULL,
                source_id TEXT NOT NULL, reason TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY(table_name,end_epoch,source_id)
            );
            CREATE TABLE IF NOT EXISTS publisher_schedule (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                next_source_index INTEGER NOT NULL
            );
        """)
        self.db.commit()

    def stage(self, event: Mapping[str, Any]) -> None:
        c = event["_cursor"]
        body = json.dumps(event, sort_keys=True, separators=(",", ":"))
        existing = self.db.execute(
            "SELECT event_json FROM event_delivery WHERE event_id=?",
            (event["event_id"],),
        ).fetchone()
        if existing is not None and existing[0] != body:
            raise PublisherError("event replay payload differs from the durable ledger")
        self.db.execute(
            "INSERT OR IGNORE INTO event_delivery(event_id,event_json,table_name,end_epoch,source_id) VALUES(?,?,?,?,?)",
            (event["event_id"], body, c["table"], c["end_epoch"], c["source_id"]),
        )
        self.db.commit()

    def acknowledge(self, event_id: str, status: int) -> str:
        row = self.db.execute(
            "SELECT table_name,end_epoch,source_id,state FROM event_delivery WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise PublisherError("acknowledgement references unknown event")
        if row[3] == "acknowledged":
            return "acknowledged"
        if row[3] == "dead_letter":
            raise PublisherError("dead-lettered event requires operator reconciliation")
        if status not in SUCCESS_ACKS:
            if status in TRANSIENT_ACKS:
                return self.fail(event_id, f"transient HTTP {status}")
            return self.fail(event_id, f"permanent HTTP {status}", permanent=True)
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "UPDATE event_delivery SET state='acknowledged',acknowledged_at=? "
            "WHERE event_id=? AND state IN ('pending','retry')",
            (now, event_id),
        )
        self.db.execute(
            "INSERT INTO publisher_cursor(table_name,end_epoch,source_id) VALUES(?,?,?) "
            "ON CONFLICT(table_name) DO UPDATE SET "
            "end_epoch=excluded.end_epoch,source_id=excluded.source_id "
            "WHERE (excluded.end_epoch,excluded.source_id) > "
            "(publisher_cursor.end_epoch,publisher_cursor.source_id)",
            row[:3],
        )
        self.db.commit()
        return "acknowledged"

    def fail(self, event_id: str, error: str, permanent: bool = False) -> str:
        row = self.db.execute(
            "SELECT attempts,state FROM event_delivery WHERE event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise PublisherError("failure references unknown event")
        if row[1] in ("acknowledged", "dead_letter"):
            raise PublisherError("terminal delivery state cannot be changed")
        attempts = int(row[0]) + 1
        state = "dead_letter" if permanent or attempts >= self.max_attempts else "retry"
        self.db.execute(
            "UPDATE event_delivery SET attempts=?,state=?,last_error=? "
            "WHERE event_id=? AND state IN ('pending','retry')",
            (attempts, state, str(error)[:500], event_id),
        )
        self.db.commit()
        return state

    def acknowledged_count(self) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) FROM event_delivery WHERE state='acknowledged'"
        ).fetchone()
        return int(row[0])

    def state(self, event_id: str) -> str:
        row = self.db.execute(
            "SELECT state FROM event_delivery WHERE event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise PublisherError("unknown event")
        return str(row[0])

    def pending(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT event_json FROM event_delivery WHERE state IN ('pending','retry') ORDER BY end_epoch,source_id"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def cursor(self, table: str, default: Cursor) -> Cursor:
        row = self.db.execute(
            "SELECT end_epoch,source_id FROM publisher_cursor WHERE table_name=?",
            (table,),
        ).fetchone()
        return default if row is None else Cursor(int(row[0]), str(row[1]))

    def skip(self, event: Mapping[str, Any], reason: str) -> None:
        """Durably advance past a non-deliverable source row without staging it."""
        cursor = event["_cursor"]
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT OR IGNORE INTO skipped_source_row"
            "(table_name,end_epoch,source_id,reason,recorded_at) VALUES(?,?,?,?,?)",
            (
                cursor["table"],
                cursor["end_epoch"],
                cursor["source_id"],
                reason[:200],
                now,
            ),
        )
        self.db.execute(
            "INSERT INTO publisher_cursor(table_name,end_epoch,source_id) VALUES(?,?,?) "
            "ON CONFLICT(table_name) DO UPDATE SET "
            "end_epoch=excluded.end_epoch,source_id=excluded.source_id "
            "WHERE (excluded.end_epoch,excluded.source_id) > "
            "(publisher_cursor.end_epoch,publisher_cursor.source_id)",
            (cursor["table"], cursor["end_epoch"], cursor["source_id"]),
        )
        self.db.commit()

    def claim_source_start(self, source_count: int) -> int:
        """Persistently rotate which source gets the first delivery opportunity."""
        if source_count <= 0:
            return 0
        self.db.execute(
            "INSERT OR IGNORE INTO publisher_schedule(singleton,next_source_index) VALUES(1,0)"
        )
        row = self.db.execute(
            "SELECT next_source_index FROM publisher_schedule WHERE singleton=1"
        ).fetchone()
        current = int(row[0]) % source_count
        self.db.execute(
            "UPDATE publisher_schedule SET next_source_index=? WHERE singleton=1",
            ((current + 1) % source_count,),
        )
        self.db.commit()
        return current

    def reconcile(self) -> dict[str, Any]:
        """Check that acknowledged events are represented by monotonic cursors."""
        rows = self.db.execute(
            "SELECT table_name,COUNT(*),SUM(state='acknowledged'),SUM(state='dead_letter') "
            "FROM event_delivery GROUP BY table_name"
        ).fetchall()
        drift = []
        summaries = {}
        for table, total, acknowledged, dead in rows:
            maximum = self.db.execute(
                "SELECT end_epoch,source_id FROM event_delivery "
                "WHERE table_name=? AND state='acknowledged' "
                "ORDER BY end_epoch DESC,source_id DESC LIMIT 1",
                (table,),
            ).fetchone()
            checkpoint = self.db.execute(
                "SELECT end_epoch,source_id FROM publisher_cursor WHERE table_name=?",
                (table,),
            ).fetchone()
            if maximum and (
                not checkpoint
                or Cursor(int(checkpoint[0]), str(checkpoint[1]))
                < Cursor(int(maximum[0]), str(maximum[1]))
            ):
                drift.append(table)
            summaries[table] = {
                "total": int(total),
                "acknowledged": int(acknowledged or 0),
                "dead_letter": int(dead or 0),
            }
        return {
            "status": "drift" if drift else "healthy",
            "drift_sources": drift,
            "sources": summaries,
        }

    def close(self) -> None:
        self.db.close()
