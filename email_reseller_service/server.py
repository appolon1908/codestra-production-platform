from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import ssl
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .database import Connection

DB_PATH = os.getenv("EMAIL_DATABASE_PATH", "/data/email-reseller.db")
MAX_BODY = int(os.getenv("EMAIL_MAX_REQUEST_BYTES", "262144"))
MAX_RECIPIENTS = int(os.getenv("EMAIL_MAX_RECIPIENTS", "50"))
MAX_SUBJECT = int(os.getenv("EMAIL_MAX_SUBJECT_BYTES", "998"))
MAX_TEXT = int(os.getenv("EMAIL_MAX_TEXT_BYTES", "100000"))
MAX_HTML = int(os.getenv("EMAIL_MAX_HTML_BYTES", "150000"))
RATE_PER_MINUTE = int(os.getenv("EMAIL_RATE_PER_MINUTE", "60"))
MODE = os.getenv("EMAIL_SUBMISSION_MODE", "synthetic")
EMAIL_RE = re.compile(r"^[^\s<>@,;\r\n]+@[^\s<>@,;\r\n]+\.[^\s<>@,;\r\n]+$")
ALLOWED_FIELDS = {"from", "to", "cc", "bcc", "subject", "text", "html", "reply_to", "client_reference"}
STATUSES = {"accepted", "queued", "sent", "delivered", "soft_bounce", "hard_bounce", "complained", "rejected", "failed"}
EVENT_TYPES = {
    "accepted": "email.accepted", "queued": "email.accepted", "sent": "email.sent",
    "delivered": "email.delivered", "soft_bounce": "email.bounced",
    "hard_bounce": "email.bounced", "complained": "email.complained",
    "rejected": "email.bounced", "failed": "email.bounced",
}
_rate_lock = threading.Lock()
_rate: dict[str, list[float]] = {}


class ApiError(ValueError):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect() -> Connection:
    return Connection(DB_PATH)


def initialize() -> None:
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS email_accounts(
          id TEXT PRIMARY KEY, kong_consumer_id TEXT NOT NULL UNIQUE, customer_id TEXT NOT NULL UNIQUE,
          enabled INTEGER NOT NULL DEFAULT 0, email_enabled INTEGER NOT NULL DEFAULT 0,
          currency TEXT NOT NULL DEFAULT 'USD', balance_minor INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS email_domains(
          id TEXT PRIMARY KEY, account_id TEXT NOT NULL, domain TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('pending','verified','active','suspended')),
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(account_id,domain),
          FOREIGN KEY(account_id) REFERENCES email_accounts(id));
        CREATE TABLE IF NOT EXISTS sender_identities(
          id TEXT PRIMARY KEY, account_id TEXT NOT NULL, domain_id TEXT NOT NULL, address TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(account_id,address), FOREIGN KEY(account_id) REFERENCES email_accounts(id),
          FOREIGN KEY(domain_id) REFERENCES email_domains(id));
        CREATE TABLE IF NOT EXISTS customer_limits(
          account_id TEXT PRIMARY KEY, max_recipients INTEGER NOT NULL, rate_per_minute INTEGER NOT NULL,
          daily_recipient_quota INTEGER NOT NULL, unit_price_minor INTEGER NOT NULL,
          updated_at TEXT NOT NULL, FOREIGN KEY(account_id) REFERENCES email_accounts(id));
        CREATE TABLE IF NOT EXISTS email_messages(
          id TEXT PRIMARY KEY, account_id TEXT NOT NULL, client_reference TEXT, idempotency_key TEXT NOT NULL,
          request_hash TEXT NOT NULL, sender TEXT NOT NULL, reply_to TEXT, recipients_json TEXT NOT NULL,
          recipient_count INTEGER NOT NULL, subject TEXT NOT NULL, text_body TEXT, html_body TEXT,
          status TEXT NOT NULL, raw_provider_status TEXT, provider_message_id TEXT,
          correlation_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(account_id,idempotency_key), FOREIGN KEY(account_id) REFERENCES email_accounts(id));
        CREATE INDEX IF NOT EXISTS email_messages_account_created ON email_messages(account_id,created_at);
        CREATE TABLE IF NOT EXISTS delivery_events(
          id TEXT PRIMARY KEY, account_id TEXT NOT NULL, message_id TEXT NOT NULL, event_type TEXT NOT NULL,
          canonical_status TEXT NOT NULL, raw_provider_state TEXT, provider_event_id TEXT,
          correlation_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(account_id,provider_event_id), FOREIGN KEY(message_id) REFERENCES email_messages(id));
        CREATE TABLE IF NOT EXISTS suppressions(
          id TEXT PRIMARY KEY, account_id TEXT NOT NULL, address TEXT NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('hard_bounce','complaint','unsubscribe','administrative')),
          active INTEGER NOT NULL DEFAULT 1, reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(account_id,address,kind), FOREIGN KEY(account_id) REFERENCES email_accounts(id));
        CREATE TABLE IF NOT EXISTS billing_ledger(
          id TEXT PRIMARY KEY, account_id TEXT NOT NULL, customer_id TEXT NOT NULL, message_id TEXT NOT NULL,
          recipient_count INTEGER NOT NULL, unit_price_minor INTEGER NOT NULL, total_minor INTEGER NOT NULL,
          currency TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(message_id,status), FOREIGN KEY(message_id) REFERENCES email_messages(id));
        CREATE TABLE IF NOT EXISTS audit_records(
          id TEXT PRIMARY KEY, account_id TEXT, kong_consumer_id TEXT, action TEXT NOT NULL,
          object_type TEXT NOT NULL, object_id TEXT, correlation_id TEXT,
          metadata_json TEXT NOT NULL, created_at TEXT NOT NULL);
        """)


def normalize_email(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ApiError(422, f"invalid_{field}")
    address = value.strip().lower()
    if len(address) > 320 or not EMAIL_RE.fullmatch(address):
        raise ApiError(422, f"invalid_{field}")
    return address


def recipients(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(x, str) for x in values):
        raise ApiError(422, f"invalid_{field}")
    return [normalize_email(x, field) for x in values]


def account_for(consumer: str, db: Connection) -> Any:
    row = db.execute("SELECT * FROM email_accounts WHERE kong_consumer_id=?", (consumer,)).fetchone()
    if not row:
        raise ApiError(403, "customer_account_not_found")
    if not row["enabled"]:
        raise ApiError(403, "account_disabled")
    if not row["email_enabled"]:
        raise ApiError(403, "email_service_disabled")
    return row


def rate_pass(account_id: str, limit: int) -> None:
    stamp = time.monotonic()
    with _rate_lock:
        bucket = [x for x in _rate.get(account_id, []) if x > stamp - 60]
        if len(bucket) >= limit:
            raise ApiError(429, "rate_limit_exceeded")
        bucket.append(stamp)
        _rate[account_id] = bucket


def canonical_request(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_message(consumer: str, idem: str, correlation: str, value: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not idem or len(idem) > 200 or "\r" in idem or "\n" in idem:
        raise ApiError(422, "idempotency_key_required")
    unsupported = sorted(set(value) - ALLOWED_FIELDS)
    if unsupported:
        raise ApiError(422, "unsupported_fields:" + ",".join(unsupported))
    sender = normalize_email(value.get("from"), "from")
    reply_to = normalize_email(value["reply_to"], "reply_to") if value.get("reply_to") else None
    to, cc, bcc = (recipients(value.get(name), name) for name in ("to", "cc", "bcc"))
    all_recipients = list(dict.fromkeys(to + cc + bcc))
    subject = value.get("subject")
    text_body, html_body = value.get("text"), value.get("html")
    if not isinstance(subject, str) or not subject or "\r" in subject or "\n" in subject or len(subject.encode()) > MAX_SUBJECT:
        raise ApiError(422, "invalid_subject")
    if not all_recipients:
        raise ApiError(422, "recipient_required")
    if text_body is not None and (not isinstance(text_body, str) or len(text_body.encode()) > MAX_TEXT):
        raise ApiError(413, "text_too_large")
    if html_body is not None and (not isinstance(html_body, str) or len(html_body.encode()) > MAX_HTML):
        raise ApiError(413, "html_too_large")
    if not text_body and not html_body:
        raise ApiError(422, "content_required")
    normalized = {"from": sender, "to": to, "cc": cc, "bcc": bcc, "subject": subject,
                  "text": text_body, "html": html_body, "reply_to": reply_to,
                  "client_reference": value.get("client_reference")}
    digest = canonical_request(normalized)
    with connect() as db:
        account = account_for(consumer, db)
        previous = db.execute("SELECT * FROM email_messages WHERE account_id=? AND idempotency_key=?", (account["id"], idem)).fetchone()
        if previous:
            if previous["request_hash"] != digest:
                raise ApiError(409, "idempotency_conflict")
            return public_message(previous), True
        limits = db.execute("SELECT * FROM customer_limits WHERE account_id=?", (account["id"],)).fetchone()
        if not limits:
            raise ApiError(403, "customer_limits_missing")
        max_rcpt = min(MAX_RECIPIENTS, limits["max_recipients"])
        if len(all_recipients) > max_rcpt:
            raise ApiError(422, "too_many_recipients")
        domain = sender.rsplit("@", 1)[1]
        domain_row = db.execute("SELECT * FROM email_domains WHERE account_id=? AND domain=?", (account["id"], domain)).fetchone()
        if not domain_row or domain_row["state"] not in {"verified", "active"}:
            raise ApiError(403, "sender_domain_not_active")
        identity = db.execute("SELECT 1 FROM sender_identities WHERE account_id=? AND address=? AND enabled=1", (account["id"], sender)).fetchone()
        if not identity:
            raise ApiError(403, "sender_identity_unauthorized")
        placeholders = ",".join("?" for _ in all_recipients)
        suppressed = db.execute(f"SELECT address FROM suppressions WHERE account_id=? AND active=1 AND address IN ({placeholders}) LIMIT 1", (account["id"], *all_recipients)).fetchone()
        if suppressed:
            raise ApiError(422, "recipient_suppressed")
        rate_pass(account["id"], min(RATE_PER_MINUTE, limits["rate_per_minute"]))
        today = now()[:10]
        used = db.execute("SELECT COALESCE(SUM(recipient_count),0) n FROM email_messages WHERE account_id=? AND created_at>=?", (account["id"], today)).fetchone()["n"]
        if used + len(all_recipients) > limits["daily_recipient_quota"]:
            raise ApiError(429, "quota_exceeded")
        total = len(all_recipients) * limits["unit_price_minor"]
        if account["balance_minor"] < total:
            raise ApiError(402, "insufficient_balance")
        mid, stamp = str(uuid.uuid4()), now()
        event_id, ledger_id = str(uuid.uuid4()), str(uuid.uuid4())
        status, raw = "accepted", "synthetic_accepted" if MODE == "synthetic" else "accepted"
        db.execute("""INSERT INTO email_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (mid, account["id"], value.get("client_reference"), idem, digest, sender, reply_to,
                    json.dumps({"to": to, "cc": cc, "bcc": bcc}), len(all_recipients), subject,
                    text_body, html_body, status, raw, None, correlation, stamp, stamp))
        db.execute("INSERT INTO delivery_events VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (event_id, account["id"], mid, "email.accepted", "accepted", raw, None, correlation, "{}", stamp))
        db.execute("INSERT INTO billing_ledger VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (ledger_id, account["id"], account["customer_id"], mid, len(all_recipients), limits["unit_price_minor"], total, account["currency"], "reserved", stamp, stamp))
        db.execute("UPDATE email_accounts SET balance_minor=balance_minor-?,updated_at=? WHERE id=?", (total, stamp, account["id"]))
        db.execute("INSERT INTO audit_records VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), account["id"], consumer, "email.accepted", "email_message", mid, correlation, json.dumps({"recipient_count": len(all_recipients), "mode": MODE}), stamp))
        row = db.execute("SELECT * FROM email_messages WHERE id=?", (mid,)).fetchone()
    return public_message(row), False


def public_message(row: Any) -> dict[str, Any]:
    return {"message_id": row["id"], "client_reference": row["client_reference"],
            "status": row["status"], "raw_provider_status": row["raw_provider_status"],
            "recipient_count": row["recipient_count"], "correlation_id": row["correlation_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def get_message(consumer: str, message_id: str) -> dict[str, Any]:
    with connect() as db:
        account = account_for(consumer, db)
        row = db.execute("SELECT * FROM email_messages WHERE id=? AND account_id=?", (message_id, account["id"])).fetchone()
        if not row:
            raise ApiError(404, "message_not_found")
        return public_message(row)


def record_provider_event(account_id: str, message_id: str, provider_event_id: str,
                          canonical_status: str, raw_state: str,
                          recipient: str | None = None, payload: dict[str, Any] | None = None) -> bool:
    """Persist a correlated provider event; intended for the private Klyrow ingress worker."""
    if canonical_status not in STATUSES or not provider_event_id or not raw_state:
        raise ApiError(422, "invalid_provider_event")
    stamp = now()
    with connect() as db:
        message = db.execute("SELECT * FROM email_messages WHERE id=? AND account_id=?", (message_id, account_id)).fetchone()
        if not message:
            raise ApiError(404, "message_not_found")
        if db.execute("SELECT 1 FROM delivery_events WHERE account_id=? AND provider_event_id=?", (account_id, provider_event_id)).fetchone():
            return False
        db.execute("INSERT INTO delivery_events VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (str(uuid.uuid4()), account_id, message_id, EVENT_TYPES[canonical_status], canonical_status,
                    raw_state, provider_event_id, message["correlation_id"], json.dumps(payload or {}, sort_keys=True), stamp))
        db.execute("UPDATE email_messages SET status=?,raw_provider_status=?,updated_at=? WHERE id=? AND account_id=?",
                   (canonical_status, raw_state, stamp, message_id, account_id))
        if canonical_status in {"hard_bounce", "complained"} and recipient:
            address = normalize_email(recipient, "recipient")
            kind = "hard_bounce" if canonical_status == "hard_bounce" else "complaint"
            db.execute("INSERT INTO suppressions VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_id,address,kind) DO UPDATE SET active=1,reason=excluded.reason,updated_at=excluded.updated_at",
                       (str(uuid.uuid4()), account_id, address, kind, 1, raw_state, stamp, stamp))
        db.execute("INSERT INTO audit_records VALUES(?,?,?,?,?,?,?,?,?)",
                   (str(uuid.uuid4()), account_id, None, EVENT_TYPES[canonical_status], "email_message", message_id,
                    message["correlation_id"], json.dumps({"provider_event_id": provider_event_id}), stamp))
    return True


def postal_connectivity() -> dict[str, Any]:
    url = os.getenv("KLYROW_HEALTH_URL", "https://klyrow.internal.codestra.agency:18000/v1/health")
    try:
        context = ssl.create_default_context(cafile=os.environ["KLYROW_CA_FILE"])
        context.load_cert_chain(os.environ["KLYROW_CLIENT_CERT_FILE"], os.environ["KLYROW_CLIENT_KEY_FILE"])
        with urllib.request.urlopen(url, timeout=2, context=context) as response:
            value = json.loads(response.read())
        return {"reachable": response.status == 200, "safe_mode": bool(value.get("safe_mode")), "production_gate_approved": bool(value.get("production_gate_approved"))}
    except Exception:
        return {"reachable": False, "safe_mode": None, "production_gate_approved": None}


def receive_klyrow_event(raw: bytes, headers: Any) -> tuple[dict[str, Any], bool]:
    timestamp = headers.get("X-Klyrow-Timestamp", "")
    event_id = headers.get("X-Klyrow-Event-Id", "")
    signature = headers.get("X-Klyrow-Signature", "").removeprefix("sha256=")
    supplied_key = headers.get("Authorization", "")
    secret, api_key = os.getenv("KLYROW_WEBHOOK_SECRET", ""), os.getenv("KLYROW_MIDDLEWARE_API_KEY", "")
    if not secret or not api_key or not hmac.compare_digest(supplied_key, "Bearer " + api_key):
        raise ApiError(401, "invalid_klyrow_identity")
    try:
        signed_at = int(timestamp)
    except ValueError as exc:
        raise ApiError(401, "invalid_klyrow_timestamp") from exc
    if abs(int(time.time()) - signed_at) > 300 or not event_id:
        raise ApiError(401, "expired_klyrow_event")
    expected = hmac.new(secret.encode(), timestamp.encode() + b"\n" + event_id.encode() + b"\nklyrow\n" + raw, hashlib.sha256).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(signature, expected):
        raise ApiError(401, "invalid_klyrow_signature")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "invalid_json") from exc
    if not isinstance(value, dict) or value.get("source_system") != "klyrow" or value.get("event_id") != event_id:
        raise ApiError(422, "invalid_klyrow_event")
    provider_event = str(value.get("provider_event") or value.get("event_type") or "unknown")
    canonical = {
        "email.sent": "sent", "email.delivered": "delivered", "email.bounced": "hard_bounce",
        "email.complained": "complained", "email.deferred": "soft_bounce",
    }.get(str(value.get("event")))
    if not canonical:
        raise ApiError(422, "unsupported_klyrow_event")
    message_id = str(value.get("message_id") or "")
    with connect() as db:
        message = db.execute("SELECT account_id FROM email_messages WHERE id=?", (message_id,)).fetchone()
    if not message:
        raise ApiError(404, "message_not_found")
    recipient = value.get("recipient")
    if isinstance(recipient, list):
        recipient = recipient[0] if recipient else None
    changed = record_provider_event(message["account_id"], message_id, event_id, canonical, provider_event,
                                    recipient if isinstance(recipient, str) else None,
                                    {"provider":"postal","payload_hash":hashlib.sha256(raw).hexdigest()})
    return {"accepted": True, "duplicate": not changed, "event_id": event_id, "status": canonical}, changed


class Handler(BaseHTTPRequestHandler):
    server_version = "CodestraEmail/1.0"

    def send_json(self, status: int, value: Any) -> None:
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def consumer(self) -> str:
        value = self.headers.get("X-Consumer-ID", "")
        if not value:
            raise ApiError(401, "kong_consumer_required")
        return value

    def body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "invalid_content_length")
        if length <= 0:
            raise ApiError(413, "request_too_large")
        if length > MAX_BODY:
            # Drain the request before responding so reverse proxies receive a
            # deterministic 413 instead of an upstream connection reset.
            remaining = length
            while remaining:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            raise ApiError(413, "request_too_large")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            raise ApiError(400, "invalid_json")
        if not isinstance(value, dict):
            raise ApiError(422, "object_required")
        return value

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/livez":
                return self.send_json(200, {"status": "alive"})
            if path in {"/ready", "/readyz"}:
                try:
                    with connect() as db:
                        db.execute("SELECT 1").fetchone()
                except Exception:
                    return self.send_json(503, {"status": "not_ready", "postgresql": "unavailable"})
                return self.send_json(200, {"status": "ready", "postgresql": "ok", "klyrow": "disabled" if MODE == "synthetic" else "required"})
            if path in {"/health", "/v1/health"}:
                return self.send_json(200, {"status": "ok", "submission_mode": MODE, "klyrow": postal_connectivity()})
            consumer = self.consumer()
            match = re.fullmatch(r"/(?:v1/email/)?messages/([0-9a-f-]+)(?:/status)?", path)
            if not match:
                raise ApiError(404, "not_found")
            message = get_message(consumer, match.group(1))
            if path.endswith("/status"):
                message = {k: message[k] for k in ("message_id", "status", "raw_provider_status", "correlation_id", "updated_at")}
            self.send_json(200, message)
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.code})

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/internal/provider-events/klyrow":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise ApiError(400, "invalid_content_length")
                if length <= 0 or length > MAX_BODY:
                    raise ApiError(413, "request_too_large")
                value, changed = receive_klyrow_event(self.rfile.read(length), self.headers)
                return self.send_json(202 if changed else 200, value)
            if path not in {"/messages", "/v1/email/messages"}:
                raise ApiError(404, "not_found")
            message, duplicate = create_message(self.consumer(), self.headers.get("Idempotency-Key", ""), self.headers.get("X-Correlation-ID", str(uuid.uuid4())), self.body())
            self.send_json(200 if duplicate else 202, message)
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.code})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(json.dumps({"at": now(), "remote": self.client_address[0], "message": fmt % args}))


def main() -> None:
    initialize()
    ThreadingHTTPServer((os.getenv("EMAIL_BIND", "0.0.0.0"), int(os.getenv("EMAIL_PORT", "8080"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
