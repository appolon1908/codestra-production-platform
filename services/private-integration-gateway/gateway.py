#!/usr/bin/env python3
"""Bounded private gateway for provider ingress and Telnexa submission.

The service intentionally uses only the Python standard library.  Production
effects require two independent, fail-closed configuration gates; the shipped
Compose contract keeps both gates disabled.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import logging
import os
import re
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
from datetime import datetime, timezone
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
    "/api/v1/kyqra/failures": "kyqra.job.failed",
    "/api/v1/telnexa/inbound": "telnexa.sms.received",
    "/api/v1/telnexa/dlr": "telnexa.sms.delivered",
    "/api/v1/telnexa/failure": "telnexa.sms.failed",
    "/api/v1/klyrow/events": "klyrow.email.event",
    "/api/v1/klyrow/bounces": "klyrow.email.bounced",
    "/api/v1/klyrow/complaints": "klyrow.email.complained",
    "/api/v1/klyrow/unsubscribes": "klyrow.email.unsubscribed",
}
ROUTE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
DISPATCH_RECEIPT_STATES = {"queued", "retrying", "delivered", "dead_letter"}
DISPATCH_LEASE_SECONDS = 30


class DispatchOutcomeUnknown(RuntimeError):
    """The receiver may have committed the request before transport failed."""


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


def jasmin_route_secret_names(route: str) -> tuple[str, str]:
    """Return the dedicated Jasmin authority names for an approved route."""

    if ROUTE_NAME.fullmatch(route) is None:
        raise PermissionError("route_not_authorized")
    stem = "JASMIN_ROUTE_" + route.upper().replace("-", "_")
    return stem + "_API_USER", stem + "_API_PASSWORD"


def verify_dispatch_receipt(
    status: int,
    raw: bytes,
    event_id: str,
    previous_attempts: int,
    previous_error: str | None,
) -> str:
    """Authenticate a bounded control-plane ingestion result by exact content."""

    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("invalid_downstream_receipt") from error
    if not isinstance(value, dict):
        raise RuntimeError("invalid_downstream_receipt")
    if 200 <= status < 300:
        if set(value) != {"event_id", "correlation_id", "duplicate", "state"}:
            raise RuntimeError("invalid_downstream_receipt")
        if value["event_id"] != event_id:
            raise RuntimeError("downstream_event_identity_mismatch")
        if not isinstance(value["duplicate"], bool):
            raise RuntimeError("invalid_downstream_receipt")
        if (
            not isinstance(value["state"], str)
            or value["state"] not in DISPATCH_RECEIPT_STATES
        ):
            raise RuntimeError("invalid_downstream_receipt")
        correlation_id = value["correlation_id"]
        if not isinstance(correlation_id, str) or not 1 <= len(correlation_id) <= 128:
            raise RuntimeError("invalid_downstream_receipt")
        return "duplicate" if value["duplicate"] else "accepted"
    if (
        status == 409
        and previous_attempts > 0
        and previous_error == "DispatchOutcomeUnknown"
        and value == {"error": "replayed_event_id"}
    ):
        return "reconciled_replay"
    raise RuntimeError("downstream_receipt_rejected")


def forwarding_tenant(payload: dict[str, Any]) -> str:
    """Return the exact bounded tenant required by the forwarding contract."""

    tenant_id = payload.get("tenant_id")
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or len(tenant_id) > 128
    ):
        raise ValueError("tenant_id_required")
    return tenant_id


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
    middleware_forwarding_enabled: bool
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
            middleware_forwarding_enabled=env_bool(
                "MIDDLEWARE_FORWARDING_ENABLED"
            ),
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
        if self.middleware_forwarding_enabled and self.mode != "middleware":
            raise ValueError("middleware forwarding requires middleware mode")
        if self.middleware_forwarding_enabled and not self.downstream_url:
            raise ValueError("middleware forwarding requires MIDDLEWARE_EVENTS_URL")
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
                    last_error TEXT,
                    dispatch_eligible INTEGER NOT NULL DEFAULT 0
                )"""
            )
            connection.execute(
                "DROP INDEX IF EXISTS kyqra_record_unique"
            )
            connection.execute(
                """CREATE UNIQUE INDEX kyqra_record_unique
                ON events(system, entity_key)
                WHERE system='kyqra'
                  AND path='/api/v1/kyqra/results'
                  AND entity_key IS NOT NULL"""
            )
            event_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(events)").fetchall()
            }
            if "payload_sha256" not in event_columns:
                connection.execute("ALTER TABLE events ADD COLUMN payload_sha256 TEXT")
            if "dispatch_eligible" not in event_columns:
                connection.execute(
                    "ALTER TABLE events ADD COLUMN dispatch_eligible INTEGER NOT NULL DEFAULT 0"
                )
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
                    operation_token TEXT,
                    lease_expires_at REAL NOT NULL DEFAULT 0,
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
            if "operation_token" not in sms_columns:
                connection.execute(
                    "ALTER TABLE sms_transactions ADD COLUMN operation_token TEXT"
                )
            if "lease_expires_at" not in sms_columns:
                connection.execute(
                    "ALTER TABLE sms_transactions ADD COLUMN lease_expires_at REAL NOT NULL DEFAULT 0"
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
        dispatch_eligible: bool,
    ) -> str:
        digest = hashlib.sha256(payload.encode()).hexdigest()
        try:
            with self.connect() as connection:
                connection.execute(
                    """INSERT INTO events(
                        event_id,system,path,entity_key,payload,payload_sha256,
                        state,created_at,dispatch_eligible
                    ) VALUES(?,?,?,?,?,?,'queued',?,?)""",
                    (
                        event_id,
                        system,
                        path,
                        entity_key,
                        payload,
                        digest,
                        now,
                        int(dispatch_eligible),
                    ),
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
                        WHERE system=? AND path=? AND entity_key=?""",
                        (system, path, entity_key),
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

    def reserve_sms(self, values: tuple[Any, ...]) -> tuple[bool, sqlite3.Row]:
        try:
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
            created = True
        except sqlite3.IntegrityError:
            created = False
        row = self.sms_by_idempotency(str(values[1]), str(values[2]))
        if row is None:
            raise RuntimeError("SMS reservation read-back failed")
        return created, row

    def complete_sms(
        self,
        adapter_message_id: str,
        *,
        operation_token: str,
        expected_state: str,
        state: str,
        jasmin_dependency: str,
        carrier_submitted: bool,
        provider_message_id: str | None,
        provider_response_sha256: str | None,
    ) -> sqlite3.Row:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE sms_transactions
                SET state=?,jasmin_dependency=?,carrier_submitted=?,provider_message_id=?,
                    provider_response_sha256=?,operation_token=NULL,lease_expires_at=0
                WHERE adapter_message_id=? AND state=? AND operation_token=?""",
                (
                    state,
                    jasmin_dependency,
                    int(carrier_submitted),
                    provider_message_id,
                    provider_response_sha256,
                    adapter_message_id,
                    expected_state,
                    operation_token,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("SMS completion lost its pending reservation")
            row = connection.execute(
                "SELECT * FROM sms_transactions WHERE adapter_message_id=?",
                (adapter_message_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("SMS completion read-back failed")
        return row

    def claim_sms(
        self,
        adapter_message_id: str,
        payload_hash: str,
        operation_token: str,
        now: float,
    ) -> tuple[bool, sqlite3.Row]:
        """Claim only a demonstrably unsubmitted reservation with a short lease."""

        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE sms_transactions
                SET state='preflight',operation_token=?,lease_expires_at=?
                WHERE adapter_message_id=? AND payload_hash=? AND (
                    state IN ('reserved','dependency_unavailable') OR
                    (state='preflight' AND lease_expires_at<=?)
                )""",
                (
                    operation_token,
                    now + 30,
                    adapter_message_id,
                    payload_hash,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sms_transactions WHERE adapter_message_id=?",
                (adapter_message_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("SMS claim read-back failed")
        return cursor.rowcount == 1, row

    def release_sms_preflight(
        self, adapter_message_id: str, operation_token: str, dependency: str
    ) -> sqlite3.Row:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE sms_transactions
                SET state='dependency_unavailable',jasmin_dependency=?,
                    operation_token=NULL,lease_expires_at=0
                WHERE adapter_message_id=? AND state='preflight' AND operation_token=?""",
                (dependency, adapter_message_id, operation_token),
            )
            row = connection.execute(
                "SELECT * FROM sms_transactions WHERE adapter_message_id=?",
                (adapter_message_id,),
            ).fetchone()
        if cursor.rowcount != 1 or row is None:
            raise RuntimeError("SMS preflight release lost ownership")
        return row

    def begin_sms_submission(
        self, adapter_message_id: str, operation_token: str
    ) -> None:
        """Cross the fail-closed boundary immediately before the carrier call."""

        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE sms_transactions
                SET state='submitting',jasmin_dependency='reachable',lease_expires_at=0
                WHERE adapter_message_id=? AND state='preflight' AND operation_token=?""",
                (adapter_message_id, operation_token),
            )
        if cursor.rowcount != 1:
            raise RuntimeError("SMS submission lost preflight ownership")

    def pending_events(self, now: float, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """SELECT * FROM events
                WHERE state IN ('queued','dispatching')
                  AND dispatch_eligible=1 AND next_attempt<=?
                ORDER BY created_at,event_id LIMIT ?""",
                (now, limit),
            ).fetchall()

    def begin_event_dispatch(
        self, event_id: str, expected_attempts: int, now: float
    ) -> sqlite3.Row:
        """Durably claim an attempt before the request can reach the receiver."""

        attempts = expected_attempts + 1
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE events
                SET state='dispatching',attempts=?,next_attempt=?,
                    last_error='DispatchOutcomeUnknown'
                WHERE event_id=? AND state IN ('queued','dispatching')
                  AND attempts=? AND dispatch_eligible=1 AND next_attempt<=?""",
                (
                    attempts,
                    now + DISPATCH_LEASE_SECONDS,
                    event_id,
                    expected_attempts,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM events WHERE event_id=?", (event_id,)
            ).fetchone()
        if cursor.rowcount != 1 or row is None:
            raise RuntimeError("event dispatch claim changed concurrently")
        return row

    def mark_event_delivered(self, event_id: str, expected_attempts: int) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE events SET state='delivered',last_error=NULL
                WHERE event_id=? AND state='dispatching' AND attempts=?
                  AND dispatch_eligible=1""",
                (event_id, expected_attempts),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("event delivery state changed concurrently")

    def mark_event_failure(
        self, event_id: str, attempts: int, next_attempt: float, error: str
    ) -> None:
        state = "dead_letter" if attempts >= 5 else "queued"
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE events
                SET state=?,attempts=?,next_attempt=?,last_error=?
                WHERE event_id=? AND state='dispatching' AND attempts=?
                  AND dispatch_eligible=1""",
                (state, attempts, next_attempt, error[:128], event_id, attempts),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("event failure state changed concurrently")

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


def validate_live_route_authorities() -> None:
    """Require a distinct credential authority for every enabled policy route."""

    enabled_routes: set[str] = set()
    route_usernames: set[str] = set()
    for policy in customer_policy().values():
        if not isinstance(policy, dict) or not policy.get("enabled", False):
            continue
        route = policy.get("route")
        if not isinstance(route, str):
            raise RuntimeError("enabled customer route is invalid")
        username_name, password_name = jasmin_route_secret_names(route)
        username = read_secret(username_name)
        password = read_secret(password_name)
        if not username or not password:
            raise RuntimeError("enabled customer route authority is unavailable")
        if route not in enabled_routes and username in route_usernames:
            raise RuntimeError("enabled routes must use distinct Jasmin authorities")
        enabled_routes.add(route)
        route_usernames.add(username)
    if not enabled_routes:
        raise RuntimeError("no enabled customer route authority is configured")


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
    jasmin_route_secret_names(route)
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
        self, route: str, sender: str, destination: str, message: str
    ) -> tuple[str, str | None]:
        username_name, password_name = jasmin_route_secret_names(route)
        username = read_secret(username_name)
        password = read_secret(password_name)
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

    def dispatch_once(self) -> int:
        """Deliver only new, explicitly eligible events with bounded retries."""

        if not self.settings.middleware_forwarding_enabled:
            return 0
        rows = self.store.pending_events(self.clock())
        for row in rows:
            previous_attempts = int(row["attempts"])
            previous_error = row["last_error"]
            attempts = previous_attempts + 1
            claimed = False
            try:
                self.store.begin_event_dispatch(
                    row["event_id"], previous_attempts, self.clock()
                )
                claimed = True
                api_key_name, hmac_secret_name, _ = SYSTEMS[row["system"]]
                api_key = read_secret(api_key_name)
                hmac_secret = read_secret(hmac_secret_name)
                if not api_key or not hmac_secret:
                    raise RuntimeError("source forwarding credentials are unavailable")
                payload = json.loads(row["payload"])
                tenant_id = forwarding_tenant(payload)
                occurred_at = payload.get("occurred_at")
                if not isinstance(occurred_at, str) or not occurred_at:
                    occurred_at = datetime.fromtimestamp(
                        float(row["created_at"]), timezone.utc
                    ).isoformat().replace("+00:00", "Z")
                event_type = EVENT_TYPES.get(row["path"])
                if event_type is None:
                    raise RuntimeError("dispatch_event_type_unmapped")
                envelope = {
                    "event_type": event_type,
                    "event_version": "1.0",
                    "occurred_at": occurred_at,
                    "tenant_id": tenant_id,
                    "idempotency_key": str(
                        payload.get("idempotency_key") or row["event_id"]
                    ),
                    "payload": payload,
                }
                for optional in ("customer_id", "correlation_id", "causation_id"):
                    if payload.get(optional) is not None:
                        envelope[optional] = payload[optional]
                body = json.dumps(
                    envelope, separators=(",", ":"), sort_keys=True
                ).encode()
                timestamp = str(int(self.clock()))
                signature = hmac.new(
                    hmac_secret.encode(),
                    canonical(timestamp, row["event_id"], row["system"], body),
                    hashlib.sha256,
                ).hexdigest()
                request = urllib.request.Request(
                    self.settings.downstream_url,
                    body,
                    {
                        "Authorization": "Bearer " + api_key,
                        "Content-Type": "application/json",
                        "X-Event-Source": row["system"],
                        "X-Timestamp": timestamp,
                        "X-Event-Id": row["event_id"],
                        "X-Signature": "sha256=" + signature,
                    },
                    method="POST",
                )
                try:
                    with self.urlopen(request, timeout=10) as response:
                        response_status = response.status
                        response_body = response.read(2049)
                except urllib.error.HTTPError as error:
                    response_status = error.code
                    try:
                        response_body = error.read(2049)
                    except Exception as response_error:
                        raise DispatchOutcomeUnknown from response_error
                except (
                    TimeoutError,
                    urllib.error.URLError,
                    ConnectionError,
                    http.client.HTTPException,
                    OSError,
                ) as error:
                    raise DispatchOutcomeUnknown from error
                if len(response_body) > 2048:
                    raise RuntimeError("downstream_response_too_large")
                receipt = verify_dispatch_receipt(
                    response_status,
                    response_body,
                    row["event_id"],
                    previous_attempts,
                    previous_error,
                )
                self.store.mark_event_delivered(row["event_id"], attempts)
                LOG.info(
                    "system=%s event_id=%s dispatch=delivered receipt=%s "
                    "payload_sha256=%s",
                    row["system"],
                    row["event_id"],
                    receipt,
                    row["payload_sha256"],
                )
            except Exception as error:
                if claimed:
                    delay = min(300, 2**attempts)
                    self.store.mark_event_failure(
                        row["event_id"],
                        attempts,
                        self.clock() + delay,
                        type(error).__name__,
                    )
                LOG.warning(
                    "system=%s event_id=%s dispatch=failed attempts=%d error=%s",
                    row["system"],
                    row["event_id"],
                    attempts,
                    type(error).__name__,
                )
        return len(rows)

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
        dispatch_eligible = (
            self.settings.middleware_forwarding_enabled and path in EVENT_TYPES
        )
        if dispatch_eligible:
            try:
                forwarding_tenant(payload)
            except ValueError:
                return 422, {"detail": "tenant_id_required"}
        entity_key = str(
            payload.get("record_id")
            if system == "kyqra" and path == "/api/v1/kyqra/results"
            else payload.get("message_id") or payload.get("job_id") or ""
        ) or None
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        result = self.store.insert_event(
            event_id,
            system,
            path,
            entity_key,
            serialized,
            self.clock(),
            dispatch_eligible,
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
        adapter_message_id = str(uuid.uuid4())
        created, reserved = self.store.reserve_sms(
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
                "unchecked",
                "reserved",
                0,
                None,
                None,
                None,
                now,
            )
        )
        if reserved["payload_hash"] != payload_sha256:
            return 409, {"detail": "idempotency_conflict"}
        operation_token = str(uuid.uuid4())
        claimed, reservation = self.store.claim_sms(
            reserved["adapter_message_id"],
            payload_sha256,
            operation_token,
            now,
        )
        if not claimed:
            return 202, {
                "accepted": True,
                "duplicate": True,
                "adapter_message_id": reservation["adapter_message_id"],
                "carrier_submitted": bool(reservation["carrier_submitted"]),
                "state": reservation["state"],
            }
        adapter_message_id = reservation["adapter_message_id"]
        dependency = self.jasmin_health()
        if dependency != "reachable":
            self.store.release_sms_preflight(
                adapter_message_id, operation_token, dependency
            )
            return 503, {"detail": "jasmin_dependency_unavailable"}
        state = "mock_accepted"
        carrier_submitted = False
        provider_message_id = None
        provider_response_sha256 = None
        if self.settings.live_submission_enabled:
            self.store.begin_sms_submission(adapter_message_id, operation_token)
            mapped, provider_response = self.submit_to_jasmin(
                route, sender, destination, message
            )
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
        completed = self.store.complete_sms(
            adapter_message_id,
            operation_token=operation_token,
            expected_state=(
                "submitting" if self.settings.live_submission_enabled else "preflight"
            ),
            state=state,
            jasmin_dependency=dependency,
            carrier_submitted=carrier_submitted,
            provider_message_id=provider_message_id,
            provider_response_sha256=provider_response_sha256,
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
            "duplicate": not created,
            "adapter_message_id": adapter_message_id,
            "carrier_submitted": bool(completed["carrier_submitted"]),
            "state": completed["state"],
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


def dispatch_worker(gateway: Gateway) -> None:
    """Continuously drain the explicitly eligible queue without blocking HTTP."""

    while True:
        try:
            dispatched = gateway.dispatch_once()
        except Exception as error:
            dispatched = 0
            LOG.error("event=dispatch_loop_failed error=%s", type(error).__name__)
        time.sleep(0.25 if dispatched else 1.0)


def start_dispatcher(gateway: Gateway) -> threading.Thread:
    """Validate downstream authority before starting the isolated worker."""

    for api_key_name, hmac_secret_name, _ in SYSTEMS.values():
        for name in (api_key_name, hmac_secret_name):
            if not read_secret(name):
                raise RuntimeError(f"{name} is unavailable")
    worker = threading.Thread(
        target=dispatch_worker,
        args=(gateway,),
        daemon=True,
        name="middleware-event-dispatcher",
    )
    worker.start()
    return worker


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
    if settings.live_submission_enabled:
        validate_live_route_authorities()
    if settings.middleware_forwarding_enabled:
        start_dispatcher(gateway)
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
