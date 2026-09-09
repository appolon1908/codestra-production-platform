"""One-time authenticated agent WebSocket boundary.

Session creation is Kong-protected on port 18103. WebSocket upgrades stay on
port 18102 for low latency, but require a 60-second one-time token whose nonce
is consumed atomically in PostgreSQL before the connection is accepted.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from websockets.asyncio.server import ServerConnection, serve
import nats
from nats.js import api as nats_api

from .core import Store
from .database import is_postgres


DB = os.getenv("CONTROL_PLANE_DB", "/data/control-plane.db")
STORE = Store(DB)
ISSUER = "codestra-realtime-session-issuer"
AUDIENCE = "codestra-agent-realtime"
TOKEN_TTL = min(60, max(15, int(os.getenv("REALTIME_SESSION_TTL_SECONDS", "60"))))
SUBJECT_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _read_secret(name: str) -> str:
    path = os.getenv(name + "_FILE", "")
    value = os.getenv(name, "")
    if not value and path:
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
    if len(value) < 32:
        raise RuntimeError(name.lower() + "_missing_or_weak")
    return value


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _ensure_nonce_table() -> None:
    if is_postgres():
        return
    with STORE.connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS realtime_session_nonce(
              nonce_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
              campaign_id TEXT NOT NULL, issued_at DOUBLE PRECISION NOT NULL,
              expires_at DOUBLE PRECISION NOT NULL, consumed_at DOUBLE PRECISION,
              source_client TEXT NOT NULL)
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS realtime_session_request(
              tenant_id TEXT NOT NULL,source_client TEXT NOT NULL,
              idempotency_key TEXT NOT NULL,request_hash TEXT NOT NULL,
              response_json TEXT NOT NULL,created_at DOUBLE PRECISION NOT NULL,
              PRIMARY KEY(tenant_id,source_client,idempotency_key))
        """)


def _token_material(
    tenant_id: str, agent_id: str, campaign_id: str,
    authenticated_subject: str, resume_cursor: int | None = None,
) -> tuple[str, float, str, int]:
    now = int(time.time())
    expires = now + TOKEN_TTL
    nonce = uuid.uuid4().hex
    payload = {
        "iss": ISSUER, "aud": AUDIENCE, "sub": agent_id,
        "tenant_id": tenant_id, "agent_id": agent_id, "campaign_id": campaign_id,
        "authenticated_subject": authenticated_subject,
        "resume_cursor": resume_cursor,
        "jti": nonce, "iat": now, "exp": expires,
    }
    encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = _b64(hmac.new(_read_secret("REALTIME_TOKEN_SECRET").encode(), encoded.encode(), hashlib.sha256).digest())
    return (encoded + "." + signature, float(expires),
            hashlib.sha256(nonce.encode()).hexdigest(), now)


def issue_token(
    tenant_id: str, agent_id: str, campaign_id: str, source_client: str,
    authenticated_subject: str,
) -> tuple[str, float]:
    token, expires, digest, issued_at = _token_material(
        tenant_id, agent_id, campaign_id, authenticated_subject
    )
    _ensure_nonce_table()
    with STORE.connect() as db:
        db.execute(
            "INSERT INTO realtime_session_nonce VALUES(?,?,?,?,?,?,NULL,?)",
            (digest, tenant_id, agent_id, campaign_id, issued_at, expires, source_client),
        )
    return token, expires


def authorized_agent_membership(
    tenant_id: str, agent_id: str, campaign_id: str, authenticated_subject: str
) -> bool:
    """Fail closed unless the Keycloak subject has an active, synced membership."""
    try:
        with STORE.connect() as db:
            if is_postgres():
                db.execute("SELECT set_config('app.tenant_id', ?, true)", (tenant_id,))
            row = db.execute(
                """SELECT 1 AS allowed
                   FROM cp_agent a
                   JOIN cp_agent_identity ai ON ai.agent_id=a.id
                   JOIN cp_membership m ON m.agent_id=a.id
                   JOIN cp_campaign c ON c.id=m.campaign_id
                   WHERE a.id=? AND c.id=? AND a.tenant_id=? AND c.tenant_id=?
                     AND m.tenant_id=? AND ai.system='KEYCLOAK'
                     AND ai.external_id=? AND ai.active=?
                     AND a.desired_state='ACTIVE'
                     AND COALESCE(a.actual_state,a.desired_state)='ACTIVE'
                     AND c.desired_state='ACTIVE'
                     AND COALESCE(c.effective_state,c.desired_state)='ACTIVE'
                     AND m.desired_state='ACTIVE'
                     AND COALESCE(m.actual_state,m.desired_state)='ACTIVE'
                     AND m.sync_status='SYNCED'
                     AND m.effective_from <= CURRENT_TIMESTAMP
                     AND (m.effective_until IS NULL OR m.effective_until > CURRENT_TIMESTAMP)
                   LIMIT 1""",
                (agent_id, campaign_id, tenant_id, tenant_id, tenant_id,
                 authenticated_subject, True),
            ).fetchone()
        return bool(row)
    except Exception:
        return False


def resolve_agent_membership(
    tenant_id: str, campaign_id: str, authenticated_subject: str
) -> str | None:
    """Derive the active agent from the authenticated Keycloak subject."""
    try:
        with STORE.connect() as db:
            if is_postgres():
                db.execute("SELECT set_config('app.tenant_id', ?, true)", (tenant_id,))
            row = db.execute(
                """SELECT a.id AS agent_id
                   FROM cp_agent a
                   JOIN cp_agent_identity ai ON ai.agent_id=a.id
                   JOIN cp_membership m ON m.agent_id=a.id
                   JOIN cp_campaign c ON c.id=m.campaign_id
                   WHERE c.id=? AND a.tenant_id=? AND c.tenant_id=?
                     AND m.tenant_id=? AND ai.system='KEYCLOAK'
                     AND ai.external_id=? AND ai.active=?
                     AND a.desired_state='ACTIVE'
                     AND COALESCE(a.actual_state,a.desired_state)='ACTIVE'
                     AND c.desired_state='ACTIVE'
                     AND COALESCE(c.effective_state,c.desired_state)='ACTIVE'
                     AND m.desired_state='ACTIVE'
                     AND COALESCE(m.actual_state,m.desired_state)='ACTIVE'
                     AND m.sync_status='SYNCED'
                     AND m.effective_from <= CURRENT_TIMESTAMP
                     AND (m.effective_until IS NULL OR m.effective_until > CURRENT_TIMESTAMP)
                   LIMIT 2""",
                (campaign_id, tenant_id, tenant_id, tenant_id,
                 authenticated_subject, True),
            ).fetchall()
        return str(row[0]["agent_id"]) if len(row) == 1 else None
    except Exception:
        return None


def issue_idempotent_session(
    tenant_id: str, agent_id: str, campaign_id: str, source_client: str,
    authenticated_subject: str, idempotency_key: str, resume_cursor: int | None,
) -> dict[str, object]:
    request_hash = hashlib.sha256(json.dumps(
        {
            "agent_id": agent_id,
            "authenticated_subject": authenticated_subject,
            "campaign_id": campaign_id,
            "resume_cursor": resume_cursor,
        },
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    token, expires, nonce_hash, issued_at = _token_material(
        tenant_id, agent_id, campaign_id, authenticated_subject, resume_cursor
    )
    contract_digest = os.getenv("CALLING_CONTRACT_DIGEST", "")
    if not re.fullmatch(r"[0-9a-f]{64}", contract_digest):
        raise RuntimeError("calling_contract_digest_missing")
    response: dict[str, object] = {
        "ticket": token,
        "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat().replace("+00:00", "Z"),
        "websocket_url": "wss://api.codestra.co/ws/agent",
        "contract_digest": contract_digest,
    }
    _ensure_nonce_table()
    with STORE.connect() as db:
        changed = db.execute(
            """INSERT INTO realtime_session_request(
                 tenant_id,source_client,idempotency_key,request_hash,response_json,created_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
            (tenant_id, source_client, idempotency_key, request_hash,
             json.dumps(response, sort_keys=True, separators=(",", ":")), time.time()),
        ).rowcount
        if changed == 1:
            db.execute(
                "INSERT INTO realtime_session_nonce VALUES(?,?,?,?,?,?,NULL,?)",
                (nonce_hash, tenant_id, agent_id, campaign_id,
                 issued_at, expires, source_client),
            )
        else:
            row = db.execute(
                """SELECT request_hash,response_json FROM realtime_session_request
                   WHERE tenant_id=? AND source_client=? AND idempotency_key=?""",
                (tenant_id, source_client, idempotency_key),
            ).fetchone()
            if not row or row["request_hash"] != request_hash:
                raise ValueError("idempotency_conflict")
            response = json.loads(row["response_json"])
    return response


def consume_token(token: str) -> dict[str, object]:
    try:
        encoded, supplied = token.split(".", 1)
        expected = _b64(hmac.new(_read_secret("REALTIME_TOKEN_SECRET").encode(), encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("invalid_signature")
        payload = json.loads(_unb64(encoded))
    except Exception as exc:
        raise ValueError("invalid_session_token") from exc
    now = time.time()
    required = {"iss", "aud", "tenant_id", "agent_id", "campaign_id", "jti", "iat", "exp"}
    if required - set(payload) or payload["iss"] != ISSUER or payload["aud"] != AUDIENCE:
        raise ValueError("invalid_session_claims")
    if float(payload["exp"]) < now or float(payload["iat"]) > now + 5:
        raise ValueError("expired_session_token")
    digest = hashlib.sha256(str(payload["jti"]).encode()).hexdigest()
    _ensure_nonce_table()
    with STORE.connect() as db:
        changed = db.execute(
            """UPDATE realtime_session_nonce SET consumed_at=?
               WHERE nonce_hash=? AND consumed_at IS NULL AND expires_at>=?
                 AND tenant_id=? AND agent_id=? AND campaign_id=?""",
            (now, digest, now, payload["tenant_id"], payload["agent_id"], payload["campaign_id"]),
        ).rowcount
    if changed != 1:
        raise ValueError("session_token_replayed_or_unknown")
    return payload


def validate_session_request(value: object) -> tuple[str, int | None]:
    if not isinstance(value, dict) or set(value) - {"campaign_id", "resume_cursor"}:
        raise ValueError("invalid_session_request")
    campaign = value.get("campaign_id")
    cursor = value.get("resume_cursor")
    if not isinstance(campaign, str) or not SUBJECT_TOKEN.fullmatch(campaign):
        raise ValueError("invalid_campaign_id")
    # JetStream sequences are unsigned 64-bit; reserve room for cursor + 1.
    if cursor is not None and (type(cursor) is not int or not 0 <= cursor < 2**64 - 1):
        raise ValueError("invalid_resume_cursor")
    return campaign, cursor


def session_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_request_field")
        result[key] = value
    return result


class SessionHandler(BaseHTTPRequestHandler):
    server_version = "CodestraRealtimeSession/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(json.dumps({"service": "realtime-session", "message": fmt % args}))

    def _json(self, status: int, value: object) -> None:
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            return self._json(200, {"status": "ok"})
        if path == "/readyz":
            try:
                with STORE.connect() as db:
                    db.execute("SELECT 1").fetchone()
            except Exception:
                return self._json(503, {"status": "not_ready", "database": "offline"})
            return self._json(200, {"status": "ready", "database": "online"})
        if path == "/version":
            return self._json(200, {
                "service": "codestra-realtime-session",
                "version": "1.0",
                "source_revision": os.getenv("SOURCE_REVISION", "unattributed"),
            })
        return self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/v1/realtime/sessions":
            return self._json(404, {"error": "not_found"})
        supplied = self.headers.get("X-Codestra-Gateway-Secret", "")
        if not hmac.compare_digest(supplied, _read_secret("KONG_CONTROL_PLANE_GATEWAY_SECRET")):
            return self._json(401, {"error": "gateway_authentication_required"})
        tenant = self.headers.get("X-Authenticated-Tenant", "")
        client = self.headers.get("X-Authenticated-Client", "")
        subject = self.headers.get("X-Authenticated-Subject", "")
        idempotency_key = self.headers.get("Idempotency-Key", "").strip()
        if not tenant or not client or not subject or not idempotency_key:
            return self._json(403, {"error": "authenticated_identity_required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 8192:
                raise ValueError("invalid_body")
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("unsupported_transfer_encoding")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete_body")
            value = json.loads(raw, object_pairs_hook=session_json_object)
            campaign_id, resume_cursor = validate_session_request(value)
            agent_id = resolve_agent_membership(tenant, campaign_id, subject)
            if not agent_id:
                return self._json(403, {"error": "active_agent_membership_required"})
            response = issue_idempotent_session(
                tenant, agent_id, campaign_id, client, subject,
                idempotency_key, resume_cursor
            )
        except (KeyError, ValueError, UnicodeError):
            return self._json(422, {"error": "invalid_session_request"})
        return self._json(201, response)


def validate_realtime_delivery(message, claims: dict[str, object], expected_subject: str) -> dict:
    digest = os.getenv("CALLING_CONTRACT_DIGEST", "")
    if (not re.fullmatch(r"[0-9a-f]{64}", digest)
            or message.subject != expected_subject
            or (message.headers or {}).get("Codestra-Contract-Digest") != digest):
        raise ValueError("realtime_delivery_binding_mismatch")
    event = json.loads(message.data, object_pairs_hook=session_json_object)
    if not isinstance(event, dict):
        raise ValueError("invalid_realtime_event")
    if any(event.get(key) != claims.get(key) for key in ("tenant_id", "campaign_id", "agent_id")):
        raise ValueError("realtime_event_scope_mismatch")
    if (type(event.get("schema_version")) is not int or event["schema_version"] != 1
            or type(event.get("sequence")) is not int or event["sequence"] < 1):
        raise ValueError("invalid_realtime_event_version")
    cursor = message.metadata.sequence.stream
    if type(cursor) is not int or not 1 <= cursor < 2**64:
        raise ValueError("invalid_realtime_stream_cursor")
    return {"cursor": cursor, "event": event}


async def forward_agent_events(connection: ServerConnection, claims: dict[str, object]) -> None:
    tokens = [str(claims[key]) for key in ("tenant_id", "campaign_id", "agent_id")]
    if not all(SUBJECT_TOKEN.fullmatch(value) for value in tokens):
        raise RuntimeError("invalid_realtime_subject")
    subject = "telephony.agent.{tenant}.{campaign}.{agent}".format(
        tenant=claims["tenant_id"], campaign=claims["campaign_id"], agent=claims["agent_id"]
    )
    if os.getenv("REALTIME_EVENT_DELIVERY_ENABLED", "false").lower() != "true":
        raise RuntimeError("realtime_event_delivery_disabled")
    credentials = os.getenv("REALTIME_NATS_CREDENTIALS_FILE", "")
    if not credentials:
        raise RuntimeError("realtime_nats_credentials_missing")
    nc = await nats.connect(
        servers=[os.getenv("REALTIME_NATS_URL", "tls://codestra-nats:4222")],
        user_credentials=credentials, connect_timeout=3, max_reconnect_attempts=3,
    )
    try:
        subscribe_options: dict[str, object] = {
            "ordered_consumer": True,
            "deliver_policy": nats_api.DeliverPolicy.NEW,
        }
        resume_cursor = claims.get("resume_cursor")
        if resume_cursor is not None:
            subscribe_options.update({
                "deliver_policy": nats_api.DeliverPolicy.BY_START_SEQUENCE,
                "opt_start_seq": int(resume_cursor) + 1,
            })
        subscription = await nc.jetstream().subscribe(subject, **subscribe_options)
        last_authorization_check = 0.0
        while True:
            now = time.monotonic()
            if now - last_authorization_check >= 30:
                allowed = await asyncio.to_thread(
                    authorized_agent_membership,
                    str(claims["tenant_id"]), str(claims["agent_id"]),
                    str(claims["campaign_id"]), str(claims["authenticated_subject"]),
                )
                if not allowed:
                    await connection.close(code=4403, reason="realtime_authorization_revoked")
                    return
                last_authorization_check = now
            try:
                message = await subscription.next_msg(timeout=1)
            except (asyncio.TimeoutError, TimeoutError):
                continue
            if len(message.data) > 262144:
                await message.term()
                continue
            try:
                envelope = validate_realtime_delivery(message, claims, subject)
            except (ValueError, TypeError, UnicodeError):
                await connection.close(code=4403, reason="realtime_event_rejected")
                return
            await asyncio.wait_for(connection.send(json.dumps(envelope, separators=(",", ":"))), timeout=5)
            await message.ack()
    finally:
        await nc.close()


async def agent_socket(connection: ServerConnection) -> None:
    requested = connection.request.headers.get("Sec-WebSocket-Protocol", "")
    protocols = [value.strip() for value in requested.split(",")]
    token_protocol = next((value for value in protocols if value.startswith("session.")), "")
    token = token_protocol.removeprefix("session.")
    try:
        claims = consume_token(token)
    except ValueError as exc:
        await connection.close(code=4401, reason=str(exc))
        return
    await connection.send(json.dumps({
        "event_type": "agent.session.ready",
        "tenant_id": claims["tenant_id"],
        "agent_id": claims["agent_id"],
        "campaign_id": claims["campaign_id"],
    }, separators=(",", ":")))
    async def receive_client() -> None:
        async for raw in connection:
            try:
                value = json.loads(raw, object_pairs_hook=session_json_object)
            except (TypeError, ValueError, UnicodeError):
                await connection.close(code=4400, reason="invalid_json")
                return
            if not isinstance(value, dict) or value != {"type": "ping"}:
                await connection.close(code=4403, reason="client_message_not_allowed")
                return
            await connection.send(json.dumps({"type": "pong", "at": int(time.time())}))

    receiver = asyncio.create_task(receive_client())
    events = asyncio.create_task(forward_agent_events(connection, claims))
    done, pending = await asyncio.wait(
        {receiver, events}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    try:
        for task in done:
            task.result()
    except Exception:
        await connection.close(code=1011, reason="realtime_transport_unavailable")


def main() -> None:
    issuer = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("REALTIME_SESSION_PORT", "18103"))), SessionHandler)
    threading.Thread(target=issuer.serve_forever, daemon=True, name="session-issuer").start()

    async def run() -> None:
        async with serve(
            agent_socket,
            "0.0.0.0",
            int(os.getenv("REALTIME_WEBSOCKET_PORT", "18102")),
            origins=["https://crm.codestra.co"],
            max_size=65536,
            max_queue=16,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
            subprotocols=["codestra-agent-v1"],
        ):
            await asyncio.Future()

    asyncio.run(run())


if __name__ == "__main__":
    main()
