"""Transactional idempotency, lead reservation and durable outbox ledger."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReservationConflict(ValueError):
    """A lead or idempotency identity conflicts with existing state."""


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class ReservationStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lead_reservation (
                    reservation_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    lead_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('ACTIVE','RELEASED')),
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_lead
                    ON lead_reservation(tenant_id, lead_id) WHERE state='ACTIVE';
                CREATE TABLE IF NOT EXISTS durable_outbox (
                    event_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('PENDING','DELIVERED','DEAD_LETTER')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )

    def reserve(
        self,
        *,
        idempotency_key: str,
        reservation_id: str,
        tenant_id: str,
        campaign_id: str,
        lead_id: str,
        owner_id: str,
    ) -> dict[str, str]:
        request = {
            "reservation_id": reservation_id,
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "lead_id": lead_id,
            "owner_id": owner_id,
        }
        digest = hashlib.sha256(_canonical(request).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        result = {**request, "state": "ACTIVE"}
        event = {
            "schema_version": "lead.reserved.v1",
            "reservation": result,
        }
        with sqlite3.connect(self.path, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT request_hash,result_json FROM idempotency WHERE key=?",
                (idempotency_key,),
            ).fetchone()
            if prior:
                if prior[0] != digest:
                    db.execute("ROLLBACK")
                    raise ReservationConflict("idempotency key reused with different request")
                db.execute("COMMIT")
                return json.loads(prior[1])
            try:
                db.execute(
                    "INSERT INTO lead_reservation VALUES (?,?,?,?,?,'ACTIVE',?)",
                    (reservation_id, tenant_id, campaign_id, lead_id, owner_id, now),
                )
            except sqlite3.IntegrityError as exc:
                db.execute("ROLLBACK")
                raise ReservationConflict("lead already has an active reservation") from exc
            db.execute(
                "INSERT INTO durable_outbox VALUES (?,?,?,'PENDING',0,?)",
                (f"lead.reserved:{reservation_id}", "lead.reserved.v1", _canonical(event), now),
            )
            db.execute(
                "INSERT INTO idempotency VALUES (?,?,?)",
                (idempotency_key, digest, _canonical(result)),
            )
            db.execute("COMMIT")
        return result

    def mark_delivered(self, event_id: str) -> None:
        with sqlite3.connect(self.path) as db:
            changed = db.execute(
                "UPDATE durable_outbox SET state='DELIVERED',attempts=attempts+1 "
                "WHERE event_id=? AND state='PENDING'",
                (event_id,),
            ).rowcount
            if changed != 1:
                raise ReservationConflict("event is missing or not pending")

    def reconcile(self) -> dict[str, int | str]:
        with sqlite3.connect(self.path) as db:
            reservations = int(db.execute("SELECT COUNT(*) FROM lead_reservation WHERE state='ACTIVE'").fetchone()[0])
            pending = int(db.execute("SELECT COUNT(*) FROM durable_outbox WHERE state='PENDING'").fetchone()[0])
            delivered = int(db.execute("SELECT COUNT(*) FROM durable_outbox WHERE state='DELIVERED'").fetchone()[0])
            missing = int(db.execute(
                "SELECT COUNT(*) FROM lead_reservation r LEFT JOIN durable_outbox o "
                "ON o.event_id='lead.reserved:' || r.reservation_id WHERE o.event_id IS NULL"
            ).fetchone()[0])
        return {
            "status": "healthy" if missing == 0 else "drift",
            "active_reservations": reservations,
            "pending": pending,
            "delivered": delivered,
            "missing_outbox": missing,
        }
