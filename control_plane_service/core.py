from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
import uuid
import urllib.parse
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
MESSAGE_STATES = {"created", "validated", "blocked", "queued", "accepted", "sent", "delivered", "failed", "rejected", "cancelled", "expired", "undeliverable", "inbound_received", "deferred", "bounced", "complained", "opened", "clicked", "unsubscribed"}


class ControlPlaneError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(timestamp: str, event_id: str, source: str, body: bytes) -> bytes:
    return b"\n".join((timestamp.encode(), event_id.encode(), source.encode(), body))


def credential_matches(supplied: str, plaintext: str, digest: str = "") -> bool:
    """Accept a legacy runtime secret or a preferred SHA-256 digest."""
    if not supplied:
        return False
    if digest:
        calculated = hashlib.sha256(supplied.encode()).hexdigest()
        return hmac.compare_digest(calculated, digest.lower())
    return bool(plaintext) and hmac.compare_digest(supplied, plaintext)


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
            CREATE TABLE IF NOT EXISTS event_deliveries(
              event_id TEXT NOT NULL, target TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
              attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT,
              PRIMARY KEY(event_id,target), FOREIGN KEY(event_id) REFERENCES events(event_id));
            CREATE TABLE IF NOT EXISTS preferences(
              tenant_id TEXT NOT NULL, contact_id TEXT NOT NULL, channel TEXT NOT NULL,
              status TEXT NOT NULL, source TEXT NOT NULL, consent_at TEXT, opted_out_at TEXT,
              reason TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(tenant_id,contact_id,channel));
            CREATE TABLE IF NOT EXISTS integrations(name TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0, changed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS circuits(name TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'closed', failures INTEGER NOT NULL DEFAULT 0, opened_at REAL);
            CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY, actor TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL, tenant_id TEXT, correlation_id TEXT, metadata TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS contacts(
              tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL, odoo_partner_id TEXT,
              phones TEXT NOT NULL DEFAULT '[]', emails TEXT NOT NULL DEFAULT '[]', identities TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL, PRIMARY KEY(tenant_id,customer_id));
            CREATE TABLE IF NOT EXISTS messages(
              message_id TEXT PRIMARY KEY, channel TEXT NOT NULL, tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL,
              external_reference TEXT, correlation_id TEXT NOT NULL, request_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
              direction TEXT NOT NULL, source_application TEXT NOT NULL, campaign_id TEXT, workflow_id TEXT,
              sender TEXT NOT NULL, recipient TEXT NOT NULL, normalized_destination TEXT NOT NULL,
              classification TEXT NOT NULL, content_metadata TEXT NOT NULL, content_payload TEXT NOT NULL, provider TEXT NOT NULL,
              downstream_provider TEXT, status TEXT NOT NULL, raw_provider_status TEXT,
              estimated_cost_minor INTEGER NOT NULL DEFAULT 0, final_cost_minor INTEGER, customer_charge_minor INTEGER,
              currency TEXT NOT NULL, provider_message_id TEXT, provider_error_code TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL, submitted_at TEXT, accepted_at TEXT, sent_at TEXT, delivered_at TEXT, failed_at TEXT,
              UNIQUE(tenant_id,idempotency_key));
            CREATE INDEX IF NOT EXISTS messages_tenant_created ON messages(tenant_id,created_at);
            CREATE INDEX IF NOT EXISTS messages_correlation ON messages(correlation_id);
            CREATE TABLE IF NOT EXISTS message_events(
              event_id TEXT PRIMARY KEY, message_id TEXT NOT NULL, tenant_id TEXT NOT NULL, event_type TEXT NOT NULL,
              normalized_status TEXT NOT NULL, raw_status TEXT, envelope TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(tenant_id,event_id), FOREIGN KEY(message_id) REFERENCES messages(message_id));
            CREATE TABLE IF NOT EXISTS suppressions(
              tenant_id TEXT NOT NULL, channel TEXT NOT NULL, destination TEXT NOT NULL, kind TEXT NOT NULL,
              reason TEXT NOT NULL, source TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, soft_bounce_count INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL, PRIMARY KEY(tenant_id,channel,destination,kind));
            CREATE TABLE IF NOT EXISTS usage_meter(
              id TEXT PRIMARY KEY, message_id TEXT NOT NULL, tenant_id TEXT NOT NULL, channel TEXT NOT NULL,
              units INTEGER NOT NULL, estimated_cost_minor INTEGER NOT NULL, final_cost_minor INTEGER,
              customer_charge_minor INTEGER, currency TEXT NOT NULL, status TEXT NOT NULL, billing_period TEXT NOT NULL,
              created_at TEXT NOT NULL, UNIQUE(message_id,status));
            CREATE TABLE IF NOT EXISTS crawler_jobs(
              job_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, correlation_id TEXT NOT NULL,
              idempotency_key TEXT NOT NULL, target_url TEXT NOT NULL, status TEXT NOT NULL,
              provider_job_id TEXT, created_at TEXT NOT NULL, UNIQUE(tenant_id,idempotency_key));
            """)
            for name in ("odoo", "n8n", "kyqra", "telnexa", "klyrow"):
                db.execute("INSERT OR IGNORE INTO integrations VALUES(?,0,?)", (name, now_iso()))
                db.execute("INSERT OR IGNORE INTO circuits(name) VALUES(?)", (name,))

    def create_crawler_job(self, value: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        required = ("tenant_id", "correlation_id", "idempotency_key", "target_url")
        if any(not value.get(key) for key in required):
            raise ControlPlaneError("missing_crawler_job_fields")
        target = str(value["target_url"])
        parsed = urllib.parse.urlparse(target)
        hostname = parsed.hostname or ""
        safe_local = parsed.scheme == "http" and hostname in {"127.0.0.1", "localhost"}
        safe_reserved = parsed.scheme == "https" and (hostname == "example.test" or hostname.endswith(".example.test"))
        if not parsed.path or not (safe_local or safe_reserved):
            raise ControlPlaneError("unsafe_crawler_target")
        job = {
            "job_id": str(uuid.uuid4()), "tenant_id": str(value["tenant_id"]),
            "correlation_id": str(value["correlation_id"]), "idempotency_key": str(value["idempotency_key"]),
            "target_url": target, "status": "queued", "provider_job_id": None, "created_at": now_iso(),
        }
        try:
            with self.connect() as db:
                db.execute("INSERT INTO crawler_jobs VALUES(?,?,?,?,?,?,?,?)", tuple(job.values()))
            return job, False
        except sqlite3.IntegrityError:
            with self.connect() as db:
                row = db.execute("SELECT * FROM crawler_jobs WHERE tenant_id=? AND idempotency_key=?", (job["tenant_id"], job["idempotency_key"])).fetchone()
            if row and row["target_url"] == target:
                return dict(row), True
            raise ControlPlaneError("idempotency_conflict")

    def accept_crawler_job(self, job_id: str, tenant: str, provider_job_id: str) -> dict[str, Any]:
        with self.connect() as db:
            db.execute("UPDATE crawler_jobs SET status='accepted',provider_job_id=? WHERE job_id=? AND tenant_id=?", (provider_job_id, job_id, tenant))
            row = db.execute("SELECT * FROM crawler_jobs WHERE job_id=? AND tenant_id=?", (job_id, tenant)).fetchone()
        if not row:
            raise ControlPlaneError("crawler_job_not_found")
        return dict(row)

    def get_crawler_job(self, job_id: str, tenant: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM crawler_jobs WHERE job_id=? AND tenant_id=?", (job_id, tenant)).fetchone()
        if not row:
            raise ControlPlaneError("crawler_job_not_found")
        return dict(row)

    def ingest(self, envelope: dict[str, Any], reject_event_replay: bool = False) -> IngestResult:
        raw = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        try:
            with self.connect() as db:
                db.execute("INSERT INTO events(event_id,tenant_id,source,event_type,idempotency_key,correlation_id,envelope,created_at) VALUES(?,?,?,?,?,?,?,?)", (envelope["event_id"], envelope["tenant_id"], envelope["source"], envelope["event_type"], envelope["idempotency_key"], envelope["correlation_id"], raw, time.time()))
                targets=("n8n",) if envelope["source"]=="odoo" else ("odoo",) if envelope["source"]=="n8n" else ("odoo","n8n")
                db.executemany("INSERT INTO event_deliveries(event_id,target) VALUES(?,?)",((envelope["event_id"],target) for target in targets))
            return IngestResult(envelope["event_id"], envelope["correlation_id"], False, "queued")
        except sqlite3.IntegrityError:
            with self.connect() as db:
                if reject_event_replay and db.execute(
                    "SELECT 1 FROM events WHERE event_id=? LIMIT 1",
                    (envelope["event_id"],),
                ).fetchone():
                    raise ControlPlaneError("replayed_event_id")
                row = db.execute("SELECT event_id,correlation_id,envelope,state FROM events WHERE event_id=? OR (tenant_id=? AND source=? AND idempotency_key=?)", (envelope["event_id"], envelope["tenant_id"], envelope["source"], envelope["idempotency_key"])).fetchone()
            def producer_content(item: dict[str, Any]) -> dict[str, Any]:
                return {key: item.get(key) for key in ("event_type", "event_version", "occurred_at", "tenant_id", "customer_id", "causation_id", "idempotency_key", "payload", "metadata")}
            if row and producer_content(json.loads(row["envelope"])) == producer_content(envelope):
                return IngestResult(row["event_id"], row["correlation_id"], True, row["state"])
            raise ControlPlaneError("idempotency_conflict")

    def event_exists(self, event_id: str) -> bool:
        """Return whether an immutable producer event ID was already accepted."""
        with self.connect() as db:
            return db.execute(
                "SELECT 1 FROM events WHERE event_id=? LIMIT 1", (event_id,)
            ).fetchone() is not None

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

    def get_preferences(self, tenant: str, contact: str) -> dict[str, Any]:
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM preferences WHERE tenant_id=? AND contact_id=? ORDER BY channel", (tenant, contact))]
        return {"tenant_id": tenant, "customer_id": contact, "channels": {r["channel"]: r for r in rows}}

    def upsert_contact(self, tenant: str, customer: str, odoo_partner_id: str | None = None, phones: list[str] | None = None, emails: list[str] | None = None, identities: dict[str, Any] | None = None) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO contacts VALUES(?,?,?,?,?,?,?) ON CONFLICT(tenant_id,customer_id) DO UPDATE SET odoo_partner_id=COALESCE(excluded.odoo_partner_id,contacts.odoo_partner_id),phones=excluded.phones,emails=excluded.emails,identities=excluded.identities,updated_at=excluded.updated_at", (tenant, customer, odoo_partner_id, json.dumps(phones or []), json.dumps(emails or []), json.dumps(identities or {}, sort_keys=True), now_iso()))

    def is_suppressed(self, tenant: str, channel: str, destination: str) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM suppressions WHERE tenant_id=? AND channel=? AND destination=? AND active=1", (tenant, channel, destination)).fetchone() is not None

    def suppress(self, tenant: str, channel: str, destination: str, kind: str, reason: str, source: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?,?,?,1,0,?) ON CONFLICT(tenant_id,channel,destination,kind) DO UPDATE SET reason=excluded.reason,source=excluded.source,active=1,updated_at=excluded.updated_at", (tenant, channel, destination, kind, reason, source, now_iso()))

    def create_message(self, value: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        channel = str(value.get("channel", "")); tenant = str(value.get("tenant_id", "")); customer = str(value.get("customer_id", ""))
        if channel not in {"sms", "email"}: raise ControlPlaneError("invalid_channel")
        required = ("idempotency_key", "request_id", "correlation_id", "sender", "recipient", "source_application", "classification")
        if not tenant or not customer or any(not value.get(k) for k in required): raise ControlPlaneError("missing_message_fields")
        if value["classification"] not in {"marketing", "transactional"}: raise ControlPlaneError("invalid_classification")
        destination = normalize_destination(channel, str(value["recipient"]))
        if value["classification"] == "marketing" and not self.preference_allows(tenant, customer, channel): raise ControlPlaneError("consent_required")
        if self.is_suppressed(tenant, channel, destination): raise ControlPlaneError("destination_suppressed")
        message_id = str(uuid.uuid4()); stamp = now_iso(); provider = "telnexa" if channel == "sms" else "klyrow"
        metadata = dict(value.get("content_metadata") or {}); metadata.pop("body", None); metadata.pop("html", None)
        content_payload={key:value[key] for key in ("content","subject","template_data") if key in value}
        fields = (message_id,channel,tenant,customer,value.get("external_reference"),value["correlation_id"],value["request_id"],value["idempotency_key"],"outbound",value["source_application"],value.get("campaign_id"),value.get("workflow_id"),value["sender"],value["recipient"],destination,value["classification"],json.dumps(metadata,sort_keys=True),json.dumps(content_payload,separators=(",",":")),provider,None,"queued",None,int(value.get("estimated_cost_minor",0)),None,None,value.get("currency","USD"),None,None,0,stamp,None,None,None,None,None)
        try:
            with self.connect() as db:
                db.execute("INSERT INTO messages VALUES(" + ",".join("?" for _ in fields) + ")", fields)
                units = sms_segments(str(value.get("content", ""))) if channel == "sms" else 1
                db.execute("INSERT INTO usage_meter VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()),message_id,tenant,channel,units,int(value.get("estimated_cost_minor",0)),None,None,value.get("currency","USD"),"reserved",stamp[:7],stamp))
                self._append_message_event(db, message_id, tenant, f"{channel}.queued", "queued", "queued", value["correlation_id"])
        except sqlite3.IntegrityError:
            with self.connect() as db: row = db.execute("SELECT * FROM messages WHERE tenant_id=? AND idempotency_key=?", (tenant,value["idempotency_key"])).fetchone()
            if row and row["channel"] == channel and row["normalized_destination"] == destination and row["customer_id"] == customer: return dict(row), True
            raise ControlPlaneError("idempotency_conflict")
        return self.get_message(message_id, tenant), False

    def create_inbound_sms(self, envelope: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        payload=envelope["payload"]; tenant=str(envelope["tenant_id"]); customer=str(envelope.get("customer_id") or payload.get("customer_id") or "")
        if not customer or not payload.get("from"): raise ControlPlaneError("inbound_identity_required")
        value={"channel":"sms","tenant_id":tenant,"customer_id":customer,"request_id":str(envelope["event_id"]),"correlation_id":envelope["correlation_id"],"idempotency_key":"inbound:"+str(envelope["idempotency_key"]),"sender":str(payload["from"]),"recipient":str(payload["from"]),"source_application":"telnexa","classification":"transactional","content_metadata":{"keyword":str(payload.get("text","")).strip().upper()[:32]}}
        message,duplicate=self.create_message(value)
        if not duplicate:
            with self.connect() as db:
                db.execute("UPDATE messages SET direction='inbound',status='inbound_received' WHERE message_id=?",(message["message_id"],)); db.execute("DELETE FROM usage_meter WHERE message_id=?",(message["message_id"],))
            message=self.get_message(message["message_id"],tenant)
        return message,duplicate

    def _append_message_event(self, db: sqlite3.Connection, message_id: str, tenant: str, event_type: str, status: str, raw_status: str | None, correlation: str, event_id: str | None = None, payload: dict[str, Any] | None = None) -> bool:
        event_id = event_id or str(uuid.uuid4()); envelope = {"event_id":event_id,"event_type":event_type,"event_version":"1.0","timestamp":now_iso(),"correlation_id":correlation,"tenant_id":tenant,"message_id":message_id,"channel":event_type.split(".",1)[0],"payload":payload or {},"metadata":{}}
        try: db.execute("INSERT INTO message_events VALUES(?,?,?,?,?,?,?,?)", (event_id,message_id,tenant,event_type,status,raw_status,json.dumps(envelope,sort_keys=True),now_iso())); return True
        except sqlite3.IntegrityError: return False

    def get_message(self, message_id: str, tenant: str | None) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM messages WHERE message_id=?" + (" AND tenant_id=?" if tenant else ""), (message_id,tenant) if tenant else (message_id,)).fetchone()
        if not row: raise ControlPlaneError("message_not_found")
        result = dict(row); result["content_metadata"] = json.loads(result["content_metadata"]); result.pop("content_payload",None); return result

    def list_messages(self, tenant: str, channel: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql="SELECT * FROM messages WHERE tenant_id=?"; args:list[Any]=[tenant]
        if channel: sql+=" AND channel=?"; args.append(channel)
        if status: sql+=" AND status=?"; args.append(status)
        sql+=" ORDER BY created_at DESC LIMIT ?"; args.append(min(limit,500))
        with self.connect() as db: rows=[dict(r) for r in db.execute(sql,args)]
        for row in rows: row.pop("content_payload",None)
        return rows

    def message_events(self, message_id: str, tenant: str) -> list[dict[str, Any]]:
        self.get_message(message_id,tenant)
        with self.connect() as db: return [json.loads(r["envelope"]) for r in db.execute("SELECT envelope FROM message_events WHERE message_id=? AND tenant_id=? ORDER BY created_at",(message_id,tenant))]

    def transition_message(self, message_id: str, tenant: str, status: str, raw_status: str, event_id: str | None = None, provider_message_id: str | None = None, error_code: str | None = None, payload: dict[str, Any] | None = None) -> bool:
        if status not in MESSAGE_STATES: raise ControlPlaneError("invalid_message_status")
        message=self.get_message(message_id,tenant); stamp=now_iso(); timestamp_col={"accepted":"accepted_at","sent":"sent_at","delivered":"delivered_at","failed":"failed_at","rejected":"failed_at","bounced":"failed_at"}.get(status)
        with self.connect() as db:
            if not self._append_message_event(db,message_id,tenant,f'{message["channel"]}.{status}',status,raw_status,message["correlation_id"],event_id,payload): return False
            sql="UPDATE messages SET status=?,raw_provider_status=?,provider_message_id=COALESCE(?,provider_message_id),provider_error_code=?"; args:list[Any]=[status,raw_status,provider_message_id,error_code]
            if timestamp_col: sql+=f",{timestamp_col}=?"; args.append(stamp)
            sql+=" WHERE message_id=? AND tenant_id=?"; args.extend((message_id,tenant)); db.execute(sql,args)
        return True

    def cancel_message(self, message_id: str, tenant: str) -> dict[str, Any]:
        message=self.get_message(message_id,tenant)
        if message["status"] not in {"created","validated","queued"}: raise ControlPlaneError("message_not_cancellable")
        self.transition_message(message_id,tenant,"cancelled","operator_cancelled"); return self.get_message(message_id,tenant)

    def retry_message(self, message_id: str, tenant: str) -> dict[str, Any]:
        message=self.get_message(message_id,tenant)
        if message["status"] not in {"failed","rejected","deferred"}: raise ControlPlaneError("message_not_retryable")
        with self.connect() as db: db.execute("UPDATE messages SET status='queued',retry_count=retry_count+1,provider_error_code=NULL WHERE message_id=? AND tenant_id=?",(message_id,tenant))
        return self.get_message(message_id,tenant)

    def apply_provider_event(self, source: str, envelope: dict[str, Any]) -> bool:
        payload=envelope["payload"]; message_id=str(payload.get("message_id", "")); tenant=envelope["tenant_id"]
        raw=str(payload.get("status") or envelope["event_type"].rsplit(".",1)[-1]); status=normalize_status(source,raw)
        message=self.get_message(message_id,tenant); destination=message["normalized_destination"]
        changed=self.transition_message(message_id,tenant,status,raw,envelope["event_id"],payload.get("provider_message_id"),payload.get("error_code"),payload)
        if changed and source=="telnexa" and envelope["event_type"] in {"telnexa.sms.received","telnexa.sms.opted_out"} and str(payload.get("text","")).strip().upper() in {"STOP","UNSUBSCRIBE"}:
            self.set_preference(tenant,message["customer_id"],"sms","unsubscribed","telnexa",str(payload.get("text")).upper()); self.suppress(tenant,"sms",destination,"optout","inbound_keyword","telnexa")
        if changed and source=="klyrow" and status in {"bounced","complained","unsubscribed"}:
            self.suppress(tenant,"email",destination,status,raw,"klyrow")
            if status in {"complained","unsubscribed"}: self.set_preference(tenant,message["customer_id"],"email","unsubscribed","klyrow",status)
        return changed

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
            if cur.rowcount: db.execute("UPDATE event_deliveries SET state='queued',next_attempt=0,last_error=NULL WHERE event_id=? AND state='dead_letter'",(event_id,))
            return cur.rowcount == 1

    def pause(self, name: str, paused: bool) -> bool:
        with self.connect() as db:
            cur = db.execute("UPDATE integrations SET paused=?,changed_at=? WHERE name=?", (int(paused), now_iso(), name))
            return cur.rowcount == 1

    def circuit_allows(self, name: str, cooldown: int = 30) -> bool:
        with self.connect() as db:
            row=db.execute("SELECT state,opened_at FROM circuits WHERE name=?",(name,)).fetchone()
            if not row or row["state"]=="closed": return True
            if row["state"]=="open" and row["opened_at"] and time.time()-row["opened_at"]>=cooldown:
                db.execute("UPDATE circuits SET state='half-open' WHERE name=?",(name,)); return True
            return row["state"]=="half-open"

    def circuit_result(self, name: str, success: bool, threshold: int = 3) -> None:
        with self.connect() as db:
            row=db.execute("SELECT failures FROM circuits WHERE name=?",(name,)).fetchone(); failures=0 if success else (row["failures"] if row else 0)+1
            state="closed" if success else "open" if failures>=threshold else "closed"
            db.execute("INSERT INTO circuits(name,state,failures,opened_at) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET state=excluded.state,failures=excluded.failures,opened_at=excluded.opened_at",(name,state,failures,time.time() if state=="open" else None))

    def audit(self, actor: str, role: str, action: str, object_type: str, object_id: str, tenant: str | None, correlation: str | None, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO audit VALUES(?,?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), actor, role, action, object_type, object_id, tenant, correlation, json.dumps(metadata or {}, sort_keys=True), now_iso()))

    def metrics(self) -> str:
        with self.connect() as db:
            counts = db.execute("SELECT state,count(*) n FROM events GROUP BY state").fetchall()
            circuits = db.execute("SELECT name,state FROM circuits").fetchall()
            messages = db.execute("SELECT channel,status,count(*) n FROM messages GROUP BY channel,status").fetchall()
            suppressions = db.execute("SELECT channel,count(*) n FROM suppressions WHERE active=1 GROUP BY channel").fetchall()
            usage = db.execute("SELECT channel,sum(units) n FROM usage_meter GROUP BY channel").fetchall()
        lines = ["# TYPE codestra_control_plane_events gauge"]
        lines += [f'codestra_control_plane_events{{state="{r["state"]}"}} {r["n"]}' for r in counts]
        lines += ["# TYPE codestra_control_plane_circuit_open gauge"]
        lines += [f'codestra_control_plane_circuit_open{{dependency="{r["name"]}"}} {1 if r["state"] == "open" else 0}' for r in circuits]
        lines += ["# TYPE codestra_communications_messages_total gauge"]
        lines += [f'codestra_communications_messages_total{{channel="{r["channel"]}",status="{r["status"]}"}} {r["n"]}' for r in messages]
        lines += ["# TYPE codestra_communications_suppressions gauge"]
        lines += [f'codestra_communications_suppressions{{channel="{r["channel"]}"}} {r["n"]}' for r in suppressions]
        lines += ["# TYPE codestra_communications_usage_units gauge"]
        lines += [f'codestra_communications_usage_units{{channel="{r["channel"]}"}} {r["n"]}' for r in usage]
        return "\n".join(lines) + "\n"

    def summary(self, tenant: str | None) -> dict[str, Any]:
        where = " WHERE tenant_id=?" if tenant else ""; args = (tenant,) if tenant else ()
        with self.connect() as db:
            states = {row["state"]: row["n"] for row in db.execute("SELECT state,count(*) n FROM events" + where + " GROUP BY state", args)}
            integrations = [dict(row) for row in db.execute("SELECT * FROM integrations ORDER BY name")]
            circuits = [dict(row) for row in db.execute("SELECT * FROM circuits ORDER BY name")]
            recent = [dict(row) for row in db.execute("SELECT event_id,tenant_id,source,event_type,correlation_id,state,attempts,last_error,created_at FROM events" + where + " ORDER BY created_at DESC LIMIT 20", args)]
            message_states = {row["status"]: row["n"] for row in db.execute("SELECT status,count(*) n FROM messages" + where + " GROUP BY status", args)}
            channels = {row["channel"]: row["n"] for row in db.execute("SELECT channel,count(*) n FROM messages" + where + " GROUP BY channel", args)}
            suppressions = db.execute("SELECT count(*) FROM suppressions" + where.replace("tenant_id", "tenant_id"), args).fetchone()[0]
        return {"event_states": states, "message_states":message_states,"channel_throughput":channels,"active_suppressions":suppressions,"queue_depth": states.get("queued", 0) + states.get("retrying", 0), "dlq_depth": states.get("dead_letter", 0), "integrations": integrations, "circuits": circuits, "recent_events": recent}


def normalize_destination(channel: str, value: str) -> str:
    value=value.strip()
    if channel=="email":
        if value.count("@")!=1 or " " in value: raise ControlPlaneError("invalid_email")
        return value.lower()
    digits="".join(c for c in value if c.isdigit())
    if value.startswith("+") and 8 <= len(digits) <= 15: return "+"+digits
    raise ControlPlaneError("invalid_e164")


def sms_segments(content: str) -> int:
    unicode=any(ord(c)>127 for c in content); single,multi=(70,67) if unicode else (160,153)
    return 1 if len(content)<=single else (len(content)+multi-1)//multi


def normalize_status(source: str, raw: str) -> str:
    key=raw.lower().replace("-","_"); mapping={"success":"accepted","submitted":"accepted","delivery_success":"delivered","delivery_failed":"failed","hard_bounce":"bounced","soft_bounce":"deferred","spam_complaint":"complained","opted_out":"unsubscribed","received":"inbound_received"}
    status=mapping.get(key,key)
    if status not in MESSAGE_STATES: return "failed" if source in {"telnexa","klyrow"} else "queued"
    return status
