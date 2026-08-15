from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SOURCES = {"kyqra", "telnexa", "klyrow", "n8n", "odoo"}
EVENT_PREFIXES = {
    "kyqra": ("kyqra.",),
    "telnexa": ("telnexa.",),
    "klyrow": ("klyrow.",),
    "n8n": ("workflow.",),
    "odoo": ("customer.", "campaign."),
}
CHANNEL_EVENTS = {
    "telnexa.sms.received": "sms",
    "telnexa.sms.delivered": "sms",
    "telnexa.sms.failed": "sms",
    "klyrow.email.sent": "email",
    "klyrow.email.delivered": "email",
    "klyrow.email.bounced": "email",
    "klyrow.email.complained": "email",
    "klyrow.email.unsubscribed": "email",
}


class ControlPlaneError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(timestamp: str, event_id: str, source: str, body: bytes) -> bytes:
    return b"\n".join((timestamp.encode(), event_id.encode(), source.encode(), body))


def verify_signature(secret: str, timestamp: str, event_id: str, source: str, body: bytes, supplied: str, ttl: int = 300) -> None:
    try:
        age = abs(int(time.time()) - int(timestamp))
    except ValueError as exc:
        raise ControlPlaneError("invalid_timestamp") from exc
    if age > ttl:
        raise ControlPlaneError("expired_timestamp")
    expected = hmac.new(secret.encode(), canonical(timestamp, event_id, source, body), hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(expected, supplied.removeprefix("sha256=")):
        raise ControlPlaneError("invalid_signature")


def validate_envelope(value: dict[str, Any], source: str, event_id: str) -> dict[str, Any]:
    required = {"event_type", "event_version", "occurred_at", "tenant_id", "idempotency_key", "payload"}
    missing = sorted(required - value.keys())
    if missing:
        raise ControlPlaneError("missing_fields:" + ",".join(missing))
    if source not in SOURCES or not any(str(value["event_type"]).startswith(p) for p in EVENT_PREFIXES[source]):
        raise ControlPlaneError("unsupported_event_type")
    if value["event_version"] != "1.0":
        raise ControlPlaneError("unsupported_event_version")
    if not isinstance(value["payload"], dict):
        raise ControlPlaneError("invalid_payload")
    result = dict(value)
    result.update(
        event_id=event_id,
        source=source,
        received_at=now_iso(),
        correlation_id=value.get("correlation_id") or str(uuid.uuid4()),
        causation_id=value.get("causation_id"),
        customer_id=value.get("customer_id"),
        metadata=value.get("metadata") or {},
    )
    return result


@dataclass
class IngestResult:
    event_id: str
    correlation_id: str
    duplicate: bool
    state: str


class Store:
    def __init__(self, path: str):
        self.path = path
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS events(
              event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source TEXT NOT NULL,
              event_type TEXT NOT NULL, idempotency_key TEXT NOT NULL, correlation_id TEXT NOT NULL,
              envelope TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
              next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT, created_at REAL NOT NULL,
              UNIQUE(tenant_id, source, idempotency_key));
            CREATE INDEX IF NOT EXISTS events_state_due ON events(state,next_attempt);
            CREATE INDEX IF NOT EXISTS events_correlation ON events(correlation_id);
            CREATE TABLE IF NOT EXISTS preferences(
              tenant_id TEXT NOT NULL, contact_id TEXT NOT NULL, channel TEXT NOT NULL,
              status TEXT NOT NULL, source TEXT NOT NULL, consent_at TEXT, opted_out_at TEXT,
              reason TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(tenant_id,contact_id,channel));
            CREATE TABLE IF NOT EXISTS integrations(name TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0, changed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS circuits(name TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'closed', failures INTEGER NOT NULL DEFAULT 0, opened_at REAL);
            CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY, actor TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL, tenant_id TEXT, correlation_id TEXT, metadata TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            for name in ("odoo", "n8n", "kyqra", "telnexa", "klyrow"):
                db.execute("INSERT OR IGNORE INTO integrations VALUES(?,0,?)", (name, now_iso()))
                db.execute("INSERT OR IGNORE INTO circuits(name) VALUES(?)", (name,))

    def ingest(self, envelope: dict[str, Any]) -> IngestResult:
        raw = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        try:
            with self.connect() as db:
                db.execute("INSERT INTO events(event_id,tenant_id,source,event_type,idempotency_key,correlation_id,envelope,created_at) VALUES(?,?,?,?,?,?,?,?)", (envelope["event_id"], envelope["tenant_id"], envelope["source"], envelope["event_type"], envelope["idempotency_key"], envelope["correlation_id"], raw, time.time()))
            return IngestResult(envelope["event_id"], envelope["correlation_id"], False, "queued")
        except sqlite3.IntegrityError:
            with self.connect() as db:
                row = db.execute("SELECT event_id,correlation_id,envelope,state FROM events WHERE event_id=? OR (tenant_id=? AND source=? AND idempotency_key=?)", (envelope["event_id"], envelope["tenant_id"], envelope["source"], envelope["idempotency_key"])).fetchone()
            def producer_content(item: dict[str, Any]) -> dict[str, Any]:
                return {key: item.get(key) for key in ("event_type", "event_version", "occurred_at", "tenant_id", "customer_id", "causation_id", "idempotency_key", "payload", "metadata")}
            if row and producer_content(json.loads(row["envelope"])) == producer_content(envelope):
                return IngestResult(row["event_id"], row["correlation_id"], True, row["state"])
            raise ControlPlaneError("idempotency_conflict")

    def set_preference(self, tenant: str, contact: str, channel: str, status: str, source: str, reason: str | None = None) -> None:
        if channel not in {"sms", "email"} or status not in {"subscribed", "unsubscribed", "suppressed"}:
            raise ControlPlaneError("invalid_preference")
        stamp = now_iso()
        with self.connect() as db:
            db.execute("INSERT INTO preferences VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,contact_id,channel) DO UPDATE SET status=excluded.status,source=excluded.source,consent_at=excluded.consent_at,opted_out_at=excluded.opted_out_at,reason=excluded.reason,updated_at=excluded.updated_at", (tenant, contact, channel, status, source, stamp if status == "subscribed" else None, stamp if status != "subscribed" else None, reason, stamp))

    def preference_allows(self, tenant: str, contact: str, channel: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT status FROM preferences WHERE tenant_id=? AND contact_id=? AND channel=?", (tenant, contact, channel)).fetchone()
        return bool(row and row["status"] == "subscribed")

    def list_events(self, tenant: str | None, state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT event_id,tenant_id,source,event_type,correlation_id,state,attempts,last_error,created_at FROM events WHERE 1=1"
        args: list[Any] = []
        if tenant:
            sql += " AND tenant_id=?"; args.append(tenant)
        if state:
            sql += " AND state=?"; args.append(state)
        sql += " ORDER BY created_at DESC LIMIT ?"; args.append(min(limit, 500))
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def correlation(self, correlation_id: str, tenant: str | None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if tenant:
                rows = db.execute("SELECT * FROM events WHERE correlation_id=? AND tenant_id=? ORDER BY created_at", (correlation_id, tenant))
            else:
                rows = db.execute("SELECT * FROM events WHERE correlation_id=? ORDER BY created_at", (correlation_id,))
            return [dict(row) for row in rows]

    def retry(self, event_id: str) -> bool:
        with self.connect() as db:
            cur = db.execute("UPDATE events SET state='queued',next_attempt=0,last_error=NULL WHERE event_id=? AND state='dead_letter'", (event_id,))
            return cur.rowcount == 1

    def pause(self, name: str, paused: bool) -> bool:
        with self.connect() as db:
            cur = db.execute("UPDATE integrations SET paused=?,changed_at=? WHERE name=?", (int(paused), now_iso(), name))
            return cur.rowcount == 1

    def audit(self, actor: str, role: str, action: str, object_type: str, object_id: str, tenant: str | None, correlation: str | None, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO audit VALUES(?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), actor, role, action, object_type, object_id, tenant, correlation, json.dumps(metadata or {}, sort_keys=True), now_iso()))

    def metrics(self) -> str:
        with self.connect() as db:
            counts = db.execute("SELECT state,count(*) n FROM events GROUP BY state").fetchall()
            circuits = db.execute("SELECT name,state FROM circuits").fetchall()
        lines = ["# TYPE codestra_control_plane_events gauge"]
        lines += [f'codestra_control_plane_events{{state="{r["state"]}"}} {r["n"]}' for r in counts]
        lines += ["# TYPE codestra_control_plane_circuit_open gauge"]
        lines += [f'codestra_control_plane_circuit_open{{dependency="{r["name"]}"}} {1 if r["state"] == "open" else 0}' for r in circuits]
        return "\n".join(lines) + "\n"

    def summary(self, tenant: str | None) -> dict[str, Any]:
        where = " WHERE tenant_id=?" if tenant else ""; args = (tenant,) if tenant else ()
        with self.connect() as db:
            states = {row["state"]: row["n"] for row in db.execute("SELECT state,count(*) n FROM events" + where + " GROUP BY state", args)}
            integrations = [dict(row) for row in db.execute("SELECT * FROM integrations ORDER BY name")]
            circuits = [dict(row) for row in db.execute("SELECT * FROM circuits ORDER BY name")]
            recent = [dict(row) for row in db.execute("SELECT event_id,tenant_id,source,event_type,correlation_id,state,attempts,last_error,created_at FROM events" + where + " ORDER BY created_at DESC LIMIT 20", args)]
        return {"event_states": states, "queue_depth": states.get("queued", 0) + states.get("retrying", 0), "dlq_depth": states.get("dead_letter", 0), "integrations": integrations, "circuits": circuits, "recent_events": recent}
