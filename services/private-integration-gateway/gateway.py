#!/usr/bin/env python3
"""Bounded private gateway for provider ingress and Telnexa submission.

The service intentionally uses only the Python standard library.  Production
effects require two independent, fail-closed configuration gates; the shipped
Compose contract keeps both gates disabled.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import socket
import sqlite3
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


LOG = logging.getLogger("private_integration_gateway")
ALL_IPV4_INTERFACES = socket.inet_ntoa(bytes(4))
SYSTEMS = {
    "kyqra": ("KYQRA_MIDDLEWARE_API_KEY", "KYQRA_WEBHOOK_SECRET", "X-Kyqra"),
    "telnexa": (
        "TELNEXA_MIDDLEWARE_API_KEY",
        "TELNEXA_WEBHOOK_SECRET",
        "X-Telnexa",
    ),
    "klyrow": (
        "KLYROW_MIDDLEWARE_API_KEY",
        "KLYROW_WEBHOOK_SECRET",
        "X-Klyrow",
    ),
}
INGRESS_PATHS = {
    "kyqra": {
        "/api/v1/kyqra/jobs",
        "/api/v1/kyqra/results",
        "/api/v1/kyqra/progress",
        "/api/v1/kyqra/failures",
    },
    "telnexa": {
        "/api/v1/telnexa/inbound",
        "/api/v1/telnexa/dlr",
        "/api/v1/telnexa/failure",
        "/api/v1/telnexa/provider-status",
    },
    "klyrow": {
        "/api/v1/klyrow/campaigns",
        "/api/v1/klyrow/contacts",
        "/api/v1/klyrow/events",
        "/api/v1/klyrow/bounces",
        "/api/v1/klyrow/complaints",
        "/api/v1/klyrow/unsubscribes",
    },
}
EVENT_TYPES = {
    "/api/v1/kyqra/results": "kyqra.record.created",
    "/api/v1/kyqra/progress": "kyqra.job.completed",
    "/api/v1/telnexa/inbound": "telnexa.sms.received",
    "/api/v1/telnexa/dlr": "telnexa.sms.delivered",
    "/api/v1/telnexa/failure": "telnexa.sms.failed",
    "/api/v1/klyrow/events": "klyrow.delivery.event",
    "/api/v1/klyrow/bounces": "klyrow.email.bounced",
    "/api/v1/klyrow/complaints": "klyrow.email.complained",
    "/api/v1/klyrow/unsubscribes": "klyrow.email.unsubscribed",
}


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return normalized == "true"


def read_secret(name: str) -> str:
    """Read a secret from NAME_FILE or NAME, preferring a no-follow file."""

    file_value = os.getenv(f"{name}_FILE", "").strip()
    env_value = os.getenv(name, "")
    if file_value and env_value:
        raise ValueError(f"configure only one of {name} or {name}_FILE")
    if not file_value:
        return env_value.strip()

    path = Path(file_value)
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{name}_FILE must name a regular non-symlink file")
        if metadata.st_size <= 0 or metadata.st_size > 65536:
            raise ValueError(f"{name}_FILE has an invalid size")
        if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError(f"{name}_FILE must not be group/world writable")
        raw = os.read(descriptor, 65537)
    finally:
        os.close(descriptor)
    if len(raw) > 65536:
        raise ValueError(f"{name}_FILE has an invalid size")
    value = raw.decode("utf-8").strip()
    if not value:
        raise ValueError(f"{name}_FILE is empty")
    return value


@dataclass(frozen=True)
class Settings:
    database_path: Path
    mode: str
    listen_address: str
    webhook_ttl_seconds: int
    max_body_bytes: int
    source_commit_sha: str
    live_submission_enabled: bool
    production_delivery_authorized: bool
    production_change_id: str
    downstream_url: str
    jasmin_url: str

    @classmethod
    def from_environment(cls) -> "Settings":
        settings = cls(
            database_path=Path(os.getenv("INTEGRATION_DB", "/data/integration.db")),
            mode=os.getenv("GATEWAY_MODE", "middleware").strip(),
            listen_address=os.getenv("LISTEN_ADDRESS", ALL_IPV4_INTERFACES).strip(),
            webhook_ttl_seconds=int(os.getenv("WEBHOOK_TTL_SECONDS", "300")),
            max_body_bytes=int(os.getenv("MAX_BODY_BYTES", "262144")),
            source_commit_sha=os.getenv("SOURCE_COMMIT_SHA", "unknown").strip(),
            live_submission_enabled=env_bool("LIVE_SUBMISSION_ENABLED"),
            production_delivery_authorized=env_bool(
                "PRODUCTION_DELIVERY_AUTHORIZED"
            ),
            production_change_id=os.getenv("PRODUCTION_CHANGE_ID", "").strip(),
            downstream_url=os.getenv("MIDDLEWARE_EVENTS_URL", "").strip(),
            jasmin_url=os.getenv("JASMIN_HTTP_URL", "http://jasmin:1401").rstrip("/"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode not in {"middleware", "shared"}:
            raise ValueError("GATEWAY_MODE must be middleware or shared")
        if self.listen_address not in {ALL_IPV4_INTERFACES, "127.0.0.1"}:
            raise ValueError("LISTEN_ADDRESS must be a bounded IPv4 listener")
        if not 30 <= self.webhook_ttl_seconds <= 900:
            raise ValueError("WEBHOOK_TTL_SECONDS must be between 30 and 900")
        if not 1024 <= self.max_body_bytes <= 1048576:
            raise ValueError("MAX_BODY_BYTES must be between 1024 and 1048576")
        if self.source_commit_sha != "unknown" and (
            len(self.source_commit_sha) != 40
            or any(character not in "0123456789abcdef" for character in self.source_commit_sha)
        ):
            raise ValueError("SOURCE_COMMIT_SHA must be a lowercase 40-character SHA")
        if self.live_submission_enabled and not (
            self.production_delivery_authorized and self.production_change_id
        ):
            raise ValueError(
                "live submission requires production authorization and a change ID"
            )
        if self.downstream_url and not self.downstream_url.startswith("https://"):
            raise ValueError("MIDDLEWARE_EVENTS_URL must use HTTPS")
        parsed = urllib.parse.urlsplit(self.jasmin_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.hostname != "jasmin":
            raise ValueError("JASMIN_HTTP_URL must be the private http://jasmin endpoint")


class Store:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except PermissionError:
            pass
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS events(
                    event_id TEXT PRIMARY KEY,
                    system TEXT NOT NULL,
                    path TEXT NOT NULL,
                    entity_key TEXT,
                    payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_error TEXT
                )"""
            )
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS kyqra_record_unique
                ON events(system, entity_key)
                WHERE system='kyqra' AND entity_key IS NOT NULL"""
            )
            event_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(events)").fetchall()
            }
            if "payload_sha256" not in event_columns:
                connection.execute("ALTER TABLE events ADD COLUMN payload_sha256 TEXT")
            for row in connection.execute(
                "SELECT event_id,payload FROM events WHERE payload_sha256 IS NULL OR payload_sha256=''"
            ).fetchall():
                connection.execute(
                    "UPDATE events SET payload_sha256=? WHERE event_id=?",
                    (hashlib.sha256(row["payload"].encode()).hexdigest(), row["event_id"]),
                )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS outbound_auth_nonces(
                    nonce TEXT PRIMARY KEY,
                    authenticated_at REAL NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS sms_transactions(
                    adapter_message_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    correlation_id TEXT,
                    sender TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    logical_route TEXT NOT NULL,
                    validation_result TEXT NOT NULL,
                    jasmin_dependency TEXT NOT NULL,
                    state TEXT NOT NULL,
                    carrier_submitted INTEGER NOT NULL DEFAULT 0,
                    provider_message_id TEXT,
                    provider_response TEXT,
                    provider_response_sha256 TEXT,
                    created_at REAL NOT NULL,
                    UNIQUE(customer_id, idempotency_key)
                )"""
            )
            sms_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(sms_transactions)"
                ).fetchall()
            }
            if "provider_response_sha256" not in sms_columns:
                connection.execute(
                    "ALTER TABLE sms_transactions ADD COLUMN provider_response_sha256 TEXT"
                )
        if self.path.exists():
            self.path.chmod(0o600)

    def insert_event(
        self,
        event_id: str,
        system: str,
        path: str,
        entity_key: str | None,
        payload: str,
        now: float,
    ) -> str:
        digest = hashlib.sha256(payload.encode()).hexdigest()
        try:
            with self.connect() as connection:
                connection.execute(
                    """INSERT INTO events(
                        event_id,system,path,entity_key,payload,payload_sha256,
                        state,created_at
                    ) VALUES(?,?,?,?,?,?,'queued',?)""",
                    (event_id, system, path, entity_key, payload, digest, now),
                )
            return "accepted"
        except sqlite3.IntegrityError:
            with self.connect() as connection:
                replay = connection.execute(
                    "SELECT payload_sha256 FROM events WHERE event_id=?", (event_id,)
                ).fetchone()
            if replay is not None:
                return "replay" if replay["payload_sha256"] == digest else "conflict"
            if entity_key is not None:
                with self.connect() as connection:
                    duplicate = connection.execute(
                        """SELECT payload_sha256 FROM events
                        WHERE system=? AND entity_key=?""",
                        (system, entity_key),
                    ).fetchone()
                if duplicate is not None:
                    return "duplicate" if duplicate["payload_sha256"] == digest else "conflict"
            return "conflict"

    def reserve_nonce(self, nonce: str, now: float, ttl: int) -> bool:
        try:
            with self.connect() as connection:
                connection.execute(
                    "DELETE FROM outbound_auth_nonces WHERE authenticated_at < ?",
                    (now - (ttl * 2),),
                )
                connection.execute(
                    "INSERT INTO outbound_auth_nonces(nonce,authenticated_at) VALUES(?,?)",
                    (nonce, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def sms_by_idempotency(
        self, customer_id: str, idempotency_key: str
    ) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                """SELECT * FROM sms_transactions
                WHERE customer_id=? AND idempotency_key=?""",
                (customer_id, idempotency_key),
            ).fetchone()

    def insert_sms(self, values: tuple[Any, ...]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO sms_transactions(
                    adapter_message_id,customer_id,idempotency_key,payload_hash,
                    payload,correlation_id,sender,destination,logical_route,
                    validation_result,jasmin_dependency,state,carrier_submitted,
                    provider_message_id,provider_response,provider_response_sha256,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )

    def event_counts(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT system,state,count(*) AS count FROM events GROUP BY system,state"
            ).fetchall()
        return [dict(row) for row in rows]

    def ready(self) -> bool:
        try:
            with self.connect() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False


def canonical(timestamp: str, event_id: str, source: str, body: bytes) -> bytes:
    return (
        timestamp.encode()
        + b"\n"
        + event_id.encode()
        + b"\n"
        + source.encode()
        + b"\n"
        + body
    )


def outbound_canonical(timestamp: str, nonce: str, body: bytes) -> bytes:
    return b"POST\n/v1/messages\n" + timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body


def normalize_sender(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("sender_required")
    normalized = value.strip()
    if not normalized or len(normalized) > 15:
        raise ValueError("invalid_sender")
    if normalized.isdigit():
        return normalized
    if not normalized.isalnum() or len(normalized) > 11:
        raise ValueError("invalid_sender")
    return normalized


def normalize_destination(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("destination_required")
    normalized = value.strip().replace(" ", "")
    if (
        not normalized.startswith("+")
        or not normalized[1:].isdigit()
        or not 8 <= len(normalized[1:]) <= 15
    ):
        raise ValueError("invalid_destination")
    if normalized.startswith(("+000", "+999")):
        raise ValueError("blocked_destination")
    return normalized


def customer_policy() -> dict[str, Any]:
    raw = read_secret("TELNEXA_CUSTOMER_POLICY_JSON") or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def validate_outbound(payload: dict[str, Any]) -> tuple[str, str, str, str, str | None]:
    customer = payload.get("customer_id")
    if not isinstance(customer, str) or not customer:
        raise ValueError("customer_required")
    policy = customer_policy().get(customer)
    if not isinstance(policy, dict) or not policy.get("enabled", False):
        raise PermissionError("customer_disabled_or_unknown")
    sender = normalize_sender(payload.get("sender", payload.get("from")))
    if sender not in policy.get("senders", []):
        raise PermissionError("sender_not_authorized")
    destination = normalize_destination(payload.get("to"))
    prefixes = policy.get("destination_prefixes", [])
    if not prefixes or not all(isinstance(prefix, str) for prefix in prefixes):
        raise PermissionError("destination_route_not_authorized")
    if not any(destination.startswith(prefix) for prefix in prefixes):
        raise PermissionError("destination_route_not_authorized")
    route = policy.get("route")
    if not isinstance(route, str) or not route:
        raise PermissionError("route_not_authorized")
    correlation = payload.get("correlation_id") or payload.get("client_reference")
    if correlation is not None and (
        not isinstance(correlation, str) or not 1 <= len(correlation) <= 128
    ):
        raise ValueError("invalid_correlation_id")
    return customer, sender, destination, route, correlation


class Gateway:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        *,
        clock: Callable[[], float] = time.time,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ):
        self.settings = settings
        self.store = store
        self.clock = clock
        self.urlopen = urlopen

    def jasmin_health(self) -> str:
        try:
            with self.urlopen(f"{self.settings.jasmin_url}/ping", timeout=3) as response:
                return "reachable" if response.status == 200 else "unhealthy"
        except Exception:
            return "unreachable"

    def submit_to_jasmin(
        self, sender: str, destination: str, message: str
    ) -> tuple[str, str | None]:
        username = read_secret("JASMIN_API_USER")
        password = read_secret("JASMIN_API_PASSWORD")
        if not username or not password:
            return "transport_error", "jasmin_credentials_unavailable"
        query = urllib.parse.urlencode(
            {
                "username": username,
                "password": password,
                "from": sender,
                "to": destination,
                "content": message,
            }
        )
        try:
            with self.urlopen(
                f"{self.settings.jasmin_url}/send?{query}", timeout=5
            ) as response:
                raw = response.read(2048)
                state = "accepted" if response.status < 300 else "rejected"
        except urllib.error.HTTPError as error:
            raw = error.read(2048)
            state = "rejected"
        except TimeoutError:
            return "timeout", None
        except Exception as error:
            return "transport_error", type(error).__name__
        return state, raw.decode(errors="replace")

    def authenticate_key(self, system: str, supplied: str) -> bool:
        key_name, _, _ = SYSTEMS[system]
        expected = read_secret(key_name)
        return bool(expected) and hmac.compare_digest(
            supplied.encode(), ("Bearer " + expected).encode()
        )

    @staticmethod
    def normalize_headers(headers: dict[str, str]) -> dict[str, str]:
        return {key.lower(): value for key, value in headers.items()}

    def ingress(
        self, system: str, path: str, body: bytes, headers: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        normalized_headers = self.normalize_headers(headers)
        if not self.authenticate_key(system, normalized_headers.get("authorization", "")):
            return 401, {"detail": "invalid api key"}
        _, secret_name, prefix = SYSTEMS[system]
        timestamp = normalized_headers.get((prefix + "-Timestamp").lower(), "")
        event_id = normalized_headers.get((prefix + "-Event-Id").lower(), "")
        signature = normalized_headers.get((prefix + "-Signature").lower(), "")
        source = normalized_headers.get("x-source-system", "")
        if (
            not timestamp
            or not event_id
            or not signature
            or source != system
            or not 8 <= len(event_id) <= 128
        ):
            return 401, {"detail": "missing authentication headers"}
        try:
            timestamp_value = int(timestamp)
        except ValueError:
            return 401, {"detail": "invalid timestamp"}
        if abs(int(self.clock()) - timestamp_value) > self.settings.webhook_ttl_seconds:
            return 401, {"detail": "expired timestamp"}
        secret = read_secret(secret_name)
        expected = hmac.new(
            secret.encode(), canonical(timestamp, event_id, source, body), hashlib.sha256
        ).hexdigest()
        if not secret or not hmac.compare_digest(
            signature.removeprefix("sha256="), expected
        ):
            return 401, {"detail": "invalid signature"}
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return 422, {"detail": "invalid json"}
        if not isinstance(payload, dict):
            return 422, {"detail": "payload must be an object"}
        required = (
            {"job_id", "record_id", "source_url", "business_name", "crawl_timestamp"}
            if path == "/api/v1/kyqra/results"
            else set()
        )
        if missing := required - payload.keys():
            return 422, {"detail": "missing required fields", "fields": sorted(missing)}
        entity_key = str(
            payload.get("record_id")
            if system == "kyqra" and path == "/api/v1/kyqra/results"
            else payload.get("message_id") or payload.get("job_id") or ""
        ) or None
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        result = self.store.insert_event(
            event_id, system, path, entity_key, serialized, self.clock()
        )
        if result in {"replay", "conflict"}:
            return 409, {
                "accepted": False,
                "detail": "replayed event id" if result == "replay" else "event id conflict",
                "event_id": event_id,
            }
        if result == "duplicate":
            return 200, {"accepted": True, "duplicate": True, "event_id": event_id}
        LOG.info(
            "system=%s event_id=%s accepted=true payload_sha256=%s",
            system,
            event_id,
            hashlib.sha256(body).hexdigest(),
        )
        return 202, {"accepted": True, "duplicate": False, "event_id": event_id}

    def outbound(
        self, body: bytes, headers: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        normalized_headers = self.normalize_headers(headers)
        if not self.authenticate_key(
            "telnexa", normalized_headers.get("authorization", "")
        ):
            return 401, {"detail": "invalid api key"}
        timestamp = normalized_headers.get("x-codestra-timestamp", "")
        nonce = normalized_headers.get("x-codestra-nonce", "")
        signature = normalized_headers.get("x-codestra-signature", "").removeprefix(
            "sha256="
        )
        if not timestamp or not nonce or not signature:
            return 401, {"detail": "missing hmac authentication headers"}
        try:
            timestamp_value = int(timestamp)
        except ValueError:
            return 401, {"detail": "invalid hmac timestamp"}
        now = self.clock()
        if abs(int(now) - timestamp_value) > self.settings.webhook_ttl_seconds:
            return 401, {"detail": "expired hmac timestamp"}
        if not 16 <= len(nonce) <= 128:
            return 401, {"detail": "invalid hmac nonce"}
        secret = read_secret("TELNEXA_WEBHOOK_SECRET")
        expected = hmac.new(
            secret.encode(), outbound_canonical(timestamp, nonce, body), hashlib.sha256
        ).hexdigest()
        if not secret or not hmac.compare_digest(signature, expected):
            return 401, {"detail": "invalid hmac signature"}
        if not self.store.reserve_nonce(nonce, now, self.settings.webhook_ttl_seconds):
            return 409, {"detail": "replayed hmac nonce"}
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return 422, {"detail": "invalid json"}
        if not isinstance(payload, dict):
            return 422, {"detail": "payload must be an object"}
        required = {"customer_id", "to", "body", "idempotency_key"}
        if missing := required - payload.keys():
            return 422, {"detail": "missing required fields", "fields": sorted(missing)}
        message = payload.get("body")
        if not isinstance(message, str) or not message.strip() or len(message) > 1600:
            return 422, {"detail": "invalid_body"}
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
            return 422, {"detail": "invalid_idempotency_key"}
        try:
            customer, sender, destination, route, correlation = validate_outbound(payload)
        except ValueError as error:
            return 422, {"detail": str(error)}
        except PermissionError as error:
            return 403, {"detail": str(error)}
        canonical_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        payload_sha256 = hashlib.sha256(canonical_payload.encode()).hexdigest()
        existing = self.store.sms_by_idempotency(customer, idempotency_key)
        if existing:
            if existing["payload_hash"] != payload_sha256:
                return 409, {"detail": "idempotency_conflict"}
            return 202, {
                "accepted": True,
                "duplicate": True,
                "adapter_message_id": existing["adapter_message_id"],
                "carrier_submitted": bool(existing["carrier_submitted"]),
                "state": existing["state"],
            }
        dependency = self.jasmin_health()
        if dependency != "reachable":
            return 503, {"detail": "jasmin_dependency_unavailable"}
        adapter_message_id = str(uuid.uuid4())
        state = "mock_accepted"
        carrier_submitted = False
        provider_message_id = None
        provider_response_sha256 = None
        if self.settings.live_submission_enabled:
            mapped, provider_response = self.submit_to_jasmin(sender, destination, message)
            state = {
                "accepted": "submitted",
                "rejected": "rejected",
                "timeout": "failed",
                "transport_error": "failed",
            }[mapped]
            carrier_submitted = mapped == "accepted"
            if provider_response is not None:
                provider_response_sha256 = hashlib.sha256(
                    provider_response.encode()
                ).hexdigest()
            provider_message_id = provider_response if carrier_submitted else None
        self.store.insert_sms(
            (
                adapter_message_id,
                customer,
                idempotency_key,
                payload_sha256,
                canonical_payload,
                correlation,
                sender,
                destination,
                route,
                "valid",
                dependency,
                state,
                int(carrier_submitted),
                provider_message_id,
                None,
                provider_response_sha256,
                now,
            )
        )
        LOG.info(
            "system=telnexa adapter_message_id=%s idempotency_key_sha256=%s "
            "customer_id=%s state=%s carrier_submitted=%s",
            adapter_message_id,
            hashlib.sha256(idempotency_key.encode()).hexdigest(),
            customer,
            state,
            carrier_submitted,
        )
        return 202, {
            "accepted": True,
            "duplicate": False,
            "adapter_message_id": adapter_message_id,
            "carrier_submitted": carrier_submitted,
            "state": state,
        }


def handler_for(gateway: Gateway) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "CodestraPrivateIntegrationGateway/2"

        def log_message(self, format_string: str, *arguments: Any) -> None:
            LOG.info("system=http client=%s " + format_string, self.client_address[0], *arguments)

        def send_json(self, code: int, value: dict[str, Any]) -> None:
            raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path in {"/health", "/ready", "/version"}:
                ready = gateway.store.ready()
                value = {
                    "status": "ok" if ready else "unavailable",
                    "mode": gateway.settings.mode,
                    "source_commit_sha": gateway.settings.source_commit_sha,
                    "live_submission_enabled": gateway.settings.live_submission_enabled,
                }
                return self.send_json(200 if ready else 503, value)
            for system in SYSTEMS:
                if self.path == f"/api/v1/{system}/health":
                    value = {
                        "status": "ok",
                        "mode": gateway.settings.mode,
                        "source_commit_sha": gateway.settings.source_commit_sha,
                    }
                    if system == "telnexa" and gateway.settings.mode == "shared":
                        value["submission_dependency"] = gateway.jasmin_health()
                        value["live_submission_enabled"] = (
                            gateway.settings.live_submission_enabled
                        )
                    return self.send_json(200, value)
            if self.path == "/metrics":
                return self.send_json(200, {"events": gateway.store.event_counts()})
            return self.send_json(404, {"detail": "not found"})

        def do_POST(self) -> None:
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError:
                return self.send_json(411, {"detail": "content length required"})
            if length <= 0 or length > gateway.settings.max_body_bytes:
                return self.send_json(413, {"detail": "invalid body size"})
            body = self.rfile.read(length)
            headers = {key: value for key, value in self.headers.items()}
            if gateway.settings.mode == "shared" and self.path == "/v1/messages":
                code, value = gateway.outbound(body, headers)
                return self.send_json(code, value)
            system = next(
                (
                    name
                    for name, paths in INGRESS_PATHS.items()
                    if self.path in paths
                ),
                None,
            )
            if gateway.settings.mode != "middleware" or system is None:
                return self.send_json(404, {"detail": "not found"})
            code, value = gateway.ingress(system, self.path, body, headers)
            return self.send_json(code, value)

    return Handler


def main() -> None:
    os.umask(0o077)
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s level=%(levelname)s %(message)s",
    )
    settings = Settings.from_environment()
    store = Store(settings.database_path)
    store.initialize()
    gateway = Gateway(settings, store)
    server = ThreadingHTTPServer((settings.listen_address, 8080), handler_for(gateway))
    server.daemon_threads = True
    LOG.info(
        "event=start mode=%s source_commit_sha=%s live_submission_enabled=%s",
        settings.mode,
        settings.source_commit_sha,
        settings.live_submission_enabled,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
