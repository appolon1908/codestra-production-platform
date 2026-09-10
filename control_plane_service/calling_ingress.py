"""Private mTLS + byte-exact signed VICIdial event ingress; no live effects.

Run the optional listener explicitly with ``python -m
control_plane_service.calling_ingress``. Plain HTTP/proxy identity headers never
substitute for a verified client certificate. PostgreSQL uses migration 007.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .core import Store, now_iso
from .database import IntegrityError, is_postgres

PATH = "/internal/v1/adapters/vicidial/events"
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")
EVENT_TYPES = frozenset(
    "telephony." + name + ".v1"
    for name in (
        "call.ringing",
        "call.answered",
        "call.connected",
        "call.transferred",
        "call.completed",
        "call.missed",
        "call.dispositioned",
        "agent.status-changed",
    )
)
REQUIRED = frozenset(
    (
        "event_id",
        "type",
        "tenant_id",
        "business_unit_id",
        "campaign_id",
        "agent_id",
        "operation_id",
        "correlation_id",
        "schema_version",
        "occurred_at",
        "sequence",
    )
)
OPTIONAL = frozenset(
    (
        "odoo_user_id",
        "odoo_lead_id",
        "vicidial_user_id",
        "vicidial_campaign_id",
        "vicidial_lead_id",
        "call_unique_id",
        "linked_id",
        "disposition",
        "duration_seconds",
        "hangup_cause",
    )
)
GRANT_FIELDS = ("tenant_id", "business_unit_id", "campaign_id", "agent_id")
MAX_BODY = 524288
SCHEMA = """CREATE TABLE IF NOT EXISTS calling_ingress_receipts(
 tenant_id TEXT NOT NULL,event_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,
 body_sha256 TEXT NOT NULL,certificate_sha256 TEXT NOT NULL,receipt TEXT NOT NULL,
 PRIMARY KEY(tenant_id,event_id,idempotency_key),UNIQUE(tenant_id,idempotency_key));"""


class IngressError(ValueError):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IngressError("INVALID_ENVELOPE")
        result[key] = value
    return result


def timestamp(value: Any, *, signing: bool = False) -> datetime:
    pattern = (
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
        if signing
        else r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})"
    )
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise IngressError("INVALID_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngressError("INVALID_TIMESTAMP") from exc
    if parsed.utcoffset() is None:
        raise IngressError("INVALID_TIMESTAMP")
    return parsed


def peer_binding(connection: Any, bindings_file: str) -> tuple[str, dict[str, Any]]:
    if (
        not isinstance(connection, ssl.SSLSocket)
        or connection.context.verify_mode != ssl.CERT_REQUIRED
    ):
        raise IngressError("ADAPTER_MTLS_REQUIRED", 401)
    certificate = connection.getpeercert(binary_form=True)
    if not certificate:
        raise IngressError("ADAPTER_MTLS_REQUIRED", 401)
    fingerprint = hashlib.sha256(certificate).hexdigest()
    try:
        path = Path(bindings_file)
        if (
            not bindings_file
            or not path.is_absolute()
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > MAX_BODY
        ):
            raise ValueError("invalid binding file")
        config = json.loads(path.read_bytes(), object_pairs_hook=strict_object)
        if (
            type(config.get("version")) is not int
            or config["version"] != 1
            or not isinstance(config.get("bindings"), list)
        ):
            raise ValueError("invalid binding version")
        matches = [
            item
            for item in config["bindings"]
            if isinstance(item, dict) and item.get("certificate_sha256") == fingerprint
        ]
        if len(matches) != 1:
            raise IngressError("ADAPTER_IDENTITY_DENIED", 403)
        return fingerprint, matches[0]
    except IngressError:
        raise
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        raise IngressError("ADAPTER_BINDING_UNAVAILABLE", 503) from exc


def validate_body(
    raw: bytes, headers: Any, binding: dict[str, Any], *, now: float | None = None
) -> dict[str, Any]:
    if not raw or len(raw) > MAX_BODY:
        raise IngressError("INVALID_BODY_SIZE", 413)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=strict_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                IngressError("INVALID_ENVELOPE")
            ),
        )
    except (ValueError, UnicodeError) as exc:
        raise IngressError("INVALID_ENVELOPE") from exc
    outer_required = {
        "event_type",
        "event_version",
        "occurred_at",
        "tenant_id",
        "idempotency_key",
        "payload",
        "correlation_id",
    }
    outer_optional = {"customer_id", "causation_id", "metadata"}
    if (
        not isinstance(value, dict)
        or outer_required - value.keys()
        or value.keys() - outer_required - outer_optional
        or value["event_version"] != "1.0"
    ):
        raise IngressError("INVALID_ENVELOPE")
    payload = value["payload"]
    if (
        not isinstance(payload, dict)
        or REQUIRED - payload.keys()
        or payload.keys() - REQUIRED - OPTIONAL
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or type(payload["sequence"]) is not int
        or payload["sequence"] < 1
        or not isinstance(payload["type"], str)
        or payload["type"] not in EVENT_TYPES
    ):
        raise IngressError("INVALID_CALLING_EVENT")
    for key, item in payload.items():
        if key in {"schema_version", "sequence", "duration_seconds"}:
            if type(item) is not int or item < 0:
                raise IngressError("INVALID_CALLING_EVENT")
        elif not isinstance(item, str):
            raise IngressError("INVALID_CALLING_EVENT")
    for key in ("tenant_id", "campaign_id", "agent_id"):
        if not TOKEN.fullmatch(payload[key]):
            raise IngressError("INVALID_CALLING_EVENT")
    for key in ("event_id", "operation_id", "correlation_id"):
        try:
            if not UUID.fullmatch(payload[key]):
                raise ValueError("noncanonical UUID")
            uuid.UUID(payload[key])
        except ValueError as exc:
            raise IngressError("INVALID_CALLING_EVENT") from exc
    timestamp(payload["occurred_at"])
    for outer, inner in (
        ("event_type", "type"),
        ("occurred_at", "occurred_at"),
        ("tenant_id", "tenant_id"),
        ("correlation_id", "correlation_id"),
    ):
        if value[outer] != payload[inner]:
            raise IngressError("CALLING_FIELD_MISMATCH")
    for key in ("customer_id", "causation_id"):
        if value.get(key) is not None and not isinstance(value[key], str):
            raise IngressError("INVALID_ENVELOPE")
    if "metadata" in value and not isinstance(value["metadata"], dict):
        raise IngressError("INVALID_ENVELOPE")
    idem = value["idempotency_key"]
    if (
        not isinstance(idem, str)
        or not idem
        or len(idem) > 255
        or any(ord(c) < 32 or ord(c) == 127 for c in idem)
    ):
        raise IngressError("INVALID_IDEMPOTENCY_KEY")
    if (
        headers.get("Idempotency-Key") != idem
        or headers.get("X-Correlation-ID") != value["correlation_id"]
    ):
        raise IngressError("CALLING_FIELD_MISMATCH")
    grants = binding.get("grants")
    if not isinstance(grants, list) or not any(
        isinstance(grant, dict)
        and set(grant) == set(GRANT_FIELDS)
        and all(grant[key] == payload[key] for key in GRANT_FIELDS)
        for grant in grants
    ):
        raise IngressError("ADAPTER_SCOPE_DENIED", 403)
    stamp = headers.get("X-Codestra-Timestamp", "")
    signed_at = timestamp(stamp, signing=True).timestamp()
    if abs((time.time() if now is None else now) - signed_at) > 300:
        raise IngressError("EXPIRED_SIGNATURE", 401)
    digest = hashlib.sha256(raw).hexdigest()
    if headers.get("X-Codestra-Content-SHA256") != digest:
        raise IngressError("CONTENT_DIGEST_MISMATCH", 401)
    try:
        secret_path = Path(binding["hmac_secret_file"])
        if (
            not secret_path.is_absolute()
            or secret_path.is_symlink()
            or not secret_path.is_file()
            or secret_path.stat().st_size > 4096
        ):
            raise ValueError("invalid secret reference")
        secret = secret_path.read_bytes().strip()
        if len(secret) < 32:
            raise ValueError("weak secret")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise IngressError("ADAPTER_BINDING_UNAVAILABLE", 503) from exc
    material = "\n".join(
        ("v1", stamp, "POST", PATH, idem, payload["event_id"], digest, "")
    ).encode()
    expected = "v1=" + hmac.new(secret, material, hashlib.sha256).hexdigest()
    supplied = headers.get("X-Codestra-Signature", "")
    if (
        not isinstance(supplied, str)
        or not re.fullmatch(r"v1=[a-f0-9]{64}", supplied)
        or not hmac.compare_digest(supplied, expected)
    ):
        raise IngressError("INVALID_SIGNATURE", 401)
    return value


def persist(
    store: Store, value: dict[str, Any], raw: bytes, fingerprint: str
) -> dict[str, Any]:
    """Receipt, immutable event and all delivery intents share one transaction."""
    event_id = value["payload"]["event_id"]
    identity = (value["tenant_id"], event_id, value["idempotency_key"])
    digest = hashlib.sha256(raw).hexdigest()
    receipt = {
        "event_id": event_id,
        "idempotency_key": value["idempotency_key"],
        "accepted_at": now_iso(),
        "outcome": "DURABLY_ACCEPTED",
    }
    envelope = {
        **value,
        "event_id": event_id,
        "source": "vicidial",
        "received_at": receipt["accepted_at"],
    }
    try:
        with store.connect() as db:
            if not is_postgres():
                db.executescript(SCHEMA)
            db.execute(
                "INSERT INTO calling_ingress_receipts VALUES(?,?,?,?,?,?)",
                (*identity, digest, fingerprint, json.dumps(receipt, sort_keys=True)),
            )
            db.execute(
                """INSERT INTO events(event_id,tenant_id,source,event_type,idempotency_key,
                       correlation_id,envelope,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    value["tenant_id"],
                    "vicidial",
                    value["event_type"],
                    value["idempotency_key"],
                    value["correlation_id"],
                    json.dumps(envelope, sort_keys=True, separators=(",", ":")),
                    time.time(),
                ),
            )
            db.executemany(
                "INSERT INTO event_deliveries(event_id,target) VALUES(?,?)",
                ((event_id, target) for target in ("odoo", "n8n", "calling")),
            )
        return receipt
    except IntegrityError:
        with store.connect() as db:
            previous = db.execute(
                """SELECT body_sha256,receipt FROM calling_ingress_receipts
                                     WHERE tenant_id=? AND event_id=? AND idempotency_key=?""",
                identity,
            ).fetchone()
        if previous and hmac.compare_digest(previous["body_sha256"], digest):
            return json.loads(previous["receipt"])
        raise IngressError("IDEMPOTENCY_CONFLICT", 409) from None


def handle(handler: Any, store: Store) -> None:
    """Shared exact-path handler; transport identity is never taken from headers."""
    try:
        if handler.path != PATH:
            raise IngressError("INVALID_CANONICAL_PATH")
        if os.getenv("VICIDIAL_EVENT_INGRESS_ENABLED", "false") != "true":
            raise IngressError("ADAPTER_INGRESS_DISABLED", 503)
        fingerprint, binding = peer_binding(
            handler.connection, os.getenv("VICIDIAL_EVENT_BINDINGS_FILE", "")
        )
        for name in (
            "Content-Length",
            "Content-Type",
            "Idempotency-Key",
            "X-Correlation-ID",
            "X-Codestra-Timestamp",
            "X-Codestra-Content-SHA256",
            "X-Codestra-Signature",
        ):
            if len(handler.headers.get_all(name, [])) != 1:
                raise IngressError("INVALID_HEADERS")
        if (
            handler.headers.get("Transfer-Encoding")
            or handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise IngressError("INVALID_HEADERS")
        length_text = handler.headers.get("Content-Length", "")
        if not length_text.isascii() or not length_text.isdecimal():
            raise IngressError("INVALID_BODY_SIZE", 413)
        length = int(length_text)
        if length < 1 or length > MAX_BODY:
            raise IngressError("INVALID_BODY_SIZE", 413)
        handler.connection.settimeout(5)
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise IngressError("INVALID_BODY_SIZE")
        value = validate_body(raw, handler.headers, binding)
        handler.send_json(202, persist(store, value, raw, fingerprint))
    except IngressError as exc:
        handler.close_connection = True
        handler.send_json(exc.status, {"error": exc.code})
    except Exception:
        # Never include input bodies, credentials, database strings or paths.
        handler.close_connection = True
        handler.send_json(503, {"error": "ADAPTER_INGRESS_UNAVAILABLE"})


def main() -> None:
    if os.getenv("VICIDIAL_EVENT_INGRESS_ENABLED", "false") != "true":
        raise SystemExit("ADAPTER_INGRESS_DISABLED")
    address = ipaddress.ip_address(os.environ["VICIDIAL_EVENT_BIND_ADDRESS"])
    permitted = (
        ipaddress.ip_network(net)
        for net in (
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "::1/128",
            "fc00::/7",
        )
    )
    if not any(address in network for network in permitted):
        raise SystemExit("ADAPTER_PRIVATE_BIND_REQUIRED")
    port = int(os.environ["VICIDIAL_EVENT_BIND_PORT"])
    if not 1024 <= port <= 65535:
        raise SystemExit("ADAPTER_BIND_PORT_INVALID")
    store = Store(os.environ["CONTROL_PLANE_DB"])
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=os.environ["VICIDIAL_EVENT_CLIENT_CA_FILE"])
    context.load_cert_chain(
        os.environ["VICIDIAL_EVENT_SERVER_CERT_FILE"],
        os.environ["VICIDIAL_EVENT_SERVER_KEY_FILE"],
    )

    with make_server(str(address), port, store, context) as server:
        server.serve_forever()


def make_server(
    address: str, port: int, store: Store, context: ssl.SSLContext
) -> ThreadingHTTPServer:
    """Build a private listener; handshake timeouts apply inside request threads."""
    if context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("client certificate verification is mandatory")

    class AdapterHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path.split("?", 1)[0] != PATH:
                self.send_json(404, {"error": "NOT_FOUND"})
                return
            handle(self, store)

        def send_json(self, status: int, value: dict[str, Any]) -> None:
            data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args: Any) -> None:
            pass

    class AdapterServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ":" in address else socket.AF_INET
        daemon_threads = True

        def get_request(self):
            connection, peer = super().get_request()
            connection.settimeout(5)
            try:
                # Do not serialize client handshakes in the accept loop.
                return context.wrap_socket(
                    connection, server_side=True, do_handshake_on_connect=False
                ), peer
            except Exception:
                connection.close()
                raise

    return AdapterServer((address, port), AdapterHandler, bind_and_activate=True)


if __name__ == "__main__":
    main()
