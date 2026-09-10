"""Database-backed work leasing for horizontally scaled delivery workers."""
from __future__ import annotations

import os
import socket
import time
import uuid
from typing import Any

from .core import Store
from .database import is_postgres


LEASE_SECONDS = int(os.getenv("CONTROL_PLANE_LEASE_SECONDS", "60"))
WORKER_ID = os.getenv(
    "CONTROL_PLANE_WORKER_ID",
    f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}",
)


def _sqlite_columns(db: Any, table: str) -> set[str]:
    return {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}


def _ensure_sqlite_schema(db: Any) -> None:
    """Keep embedded tests compatible; PostgreSQL must use migration 006."""
    if is_postgres():
        return
    additions = {
        "event_deliveries": {
            "lease_owner": "TEXT",
            "lease_token": "TEXT",
            "lease_expires_at": "DOUBLE PRECISION",
        },
        "messages": {
            "lease_owner": "TEXT",
            "lease_token": "TEXT",
            "lease_expires_at": "DOUBLE PRECISION",
            "next_attempt": "DOUBLE PRECISION NOT NULL DEFAULT 0",
        },
    }
    for table, columns in additions.items():
        present = _sqlite_columns(db, table)
        for name, declaration in columns.items():
            if name not in present:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _tokens(limit: int) -> list[str]:
    return [uuid.uuid4().hex for _ in range(limit)]


def claim_event_deliveries(store: Store, limit: int = 50) -> list[dict[str, Any]]:
    now = time.time()
    expires = now + LEASE_SECONDS
    tokens = _tokens(limit)
    with store.connect() as db:
        _ensure_sqlite_schema(db)
        if is_postgres():
            rows = db.execute(
                """
                WITH candidates AS (
                  SELECT d.event_id,d.target
                  FROM event_deliveries d
                  JOIN integrations i ON i.name=d.target
                  WHERE d.state IN ('queued','retrying','leased')
                    AND d.next_attempt<=?
                    AND i.paused=0
                    AND (d.state!='leased' OR d.lease_expires_at IS NULL OR d.lease_expires_at<=?)
                  ORDER BY d.next_attempt,d.event_id,d.target
                  FOR UPDATE OF d SKIP LOCKED
                  LIMIT ?
                )
                UPDATE event_deliveries d
                SET state='leased',lease_owner=?,lease_token=md5(random()::text || clock_timestamp()::text),lease_expires_at=?
                FROM candidates c
                WHERE d.event_id=c.event_id AND d.target=c.target
                RETURNING d.event_id,d.target,d.attempts AS delivery_attempts,d.lease_token,d.lease_expires_at
                """,
                (now, now, limit, WORKER_ID, expires),
            ).fetchall()
        else:
            db.raw.execute("BEGIN IMMEDIATE")
            candidates = db.execute(
                """
                SELECT d.event_id,d.target,d.attempts AS delivery_attempts
                FROM event_deliveries d
                JOIN integrations i ON i.name=d.target
                WHERE d.state IN ('queued','retrying','leased')
                  AND d.next_attempt<=? AND i.paused=0
                  AND (d.state!='leased' OR d.lease_expires_at IS NULL OR d.lease_expires_at<=?)
                ORDER BY d.next_attempt,d.event_id,d.target LIMIT ?
                """,
                (now, now, limit),
            ).fetchall()
            rows = []
            for index, candidate in enumerate(candidates):
                token = tokens[index]
                changed = db.execute(
                    """
                    UPDATE event_deliveries
                    SET state='leased',lease_owner=?,lease_token=?,lease_expires_at=?
                    WHERE event_id=? AND target=?
                      AND (state!='leased' OR lease_expires_at IS NULL OR lease_expires_at<=?)
                    """,
                    (WORKER_ID, token, expires, candidate["event_id"], candidate["target"], now),
                ).rowcount
                if changed:
                    rows.append({**dict(candidate), "lease_token": token, "lease_expires_at": expires})
        claimed: list[dict[str, Any]] = []
        for lease in rows:
            event = db.execute("SELECT * FROM events WHERE event_id=?", (lease["event_id"],)).fetchone()
            if event:
                claimed.append({**dict(event), **dict(lease)})
        return claimed


def claim_messages(store: Store, limit: int = 50) -> list[dict[str, Any]]:
    now = time.time()
    expires = now + LEASE_SECONDS
    tokens = _tokens(limit)
    with store.connect() as db:
        _ensure_sqlite_schema(db)
        if is_postgres():
            rows = db.execute(
                """
                WITH candidates AS (
                  SELECT m.message_id
                  FROM messages m
                  JOIN integrations i ON i.name=m.provider
                  WHERE m.status IN ('queued','leased') AND m.next_attempt<=? AND i.paused=0
                    AND (m.status!='leased' OR m.lease_expires_at IS NULL OR m.lease_expires_at<=?)
                  ORDER BY m.next_attempt,m.created_at,m.message_id
                  FOR UPDATE OF m SKIP LOCKED
                  LIMIT ?
                )
                UPDATE messages m
                SET status='leased',lease_owner=?,lease_token=md5(random()::text || clock_timestamp()::text),lease_expires_at=?
                FROM candidates c WHERE m.message_id=c.message_id
                RETURNING m.*
                """,
                (now, now, limit, WORKER_ID, expires),
            ).fetchall()
            return [dict(row) for row in rows]
        db.raw.execute("BEGIN IMMEDIATE")
        candidates = db.execute(
            """
            SELECT m.* FROM messages m JOIN integrations i ON i.name=m.provider
            WHERE m.status IN ('queued','leased') AND m.next_attempt<=? AND i.paused=0
              AND (m.status!='leased' OR m.lease_expires_at IS NULL OR m.lease_expires_at<=?)
            ORDER BY m.next_attempt,m.created_at,m.message_id LIMIT ?
            """,
            (now, now, limit),
        ).fetchall()
        claimed = []
        for index, candidate in enumerate(candidates):
            token = tokens[index]
            changed = db.execute(
                """UPDATE messages SET status='leased',lease_owner=?,lease_token=?,lease_expires_at=?
                WHERE message_id=? AND (status!='leased' OR lease_expires_at IS NULL OR lease_expires_at<=?)""",
                (WORKER_ID, token, expires, candidate["message_id"], now),
            ).rowcount
            if changed:
                claimed.append({**dict(candidate), "status": "leased", "lease_owner": WORKER_ID,
                                "lease_token": token, "lease_expires_at": expires})
        return claimed


def owned_where() -> str:
    """SQL fragment used on every terminal update to fence stale workers."""
    return "lease_owner=? AND lease_token=?"


def renew_event_lease(store: Store, row: dict[str, Any]) -> bool:
    with store.connect() as db:
        changed = db.execute(
            """UPDATE event_deliveries SET lease_expires_at=?
               WHERE event_id=? AND target=? AND state='leased' AND lease_owner=? AND lease_token=?""",
            (time.time() + LEASE_SECONDS, row["event_id"], row["target"], WORKER_ID, row["lease_token"]),
        ).rowcount
    return changed == 1


def renew_message_lease(store: Store, row: dict[str, Any]) -> bool:
    with store.connect() as db:
        changed = db.execute(
            """UPDATE messages SET lease_expires_at=?
               WHERE message_id=? AND status='leased' AND lease_owner=? AND lease_token=?""",
            (time.time() + LEASE_SECONDS, row["message_id"], WORKER_ID, row["lease_token"]),
        ).rowcount
    return changed == 1
