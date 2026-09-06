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
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from websockets.asyncio.server import ServerConnection, serve

from .core import Store
from .database import is_postgres


DB = os.getenv("CONTROL_PLANE_DB", "/data/control-plane.db")
STORE = Store(DB)
ISSUER = "codestra-realtime-session-issuer"
AUDIENCE = "codestra-agent-realtime"
TOKEN_TTL = min(60, max(15, int(os.getenv("REALTIME_SESSION_TTL_SECONDS", "60"))))


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


def issue_token(tenant_id: str, agent_id: str, campaign_id: str, source_client: str) -> tuple[str, float]:
    now = int(time.time())
    expires = now + TOKEN_TTL
    nonce = uuid.uuid4().hex
    payload = {
        "iss": ISSUER, "aud": AUDIENCE, "sub": agent_id,
        "tenant_id": tenant_id, "agent_id": agent_id, "campaign_id": campaign_id,
        "jti": nonce, "iat": now, "exp": expires,
    }
    encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = _b64(hmac.new(_read_secret("REALTIME_TOKEN_SECRET").encode(), encoded.encode(), hashlib.sha256).digest())
    digest = hashlib.sha256(nonce.encode()).hexdigest()
    _ensure_nonce_table()
    with STORE.connect() as db:
        db.execute(
            "INSERT INTO realtime_session_nonce VALUES(?,?,?,?,?,?,NULL,?)",
            (digest, tenant_id, agent_id, campaign_id, now, expires, source_client),
        )
    return encoded + "." + signature, float(expires)


def authorized_agent_membership(
    tenant_id: str, agent_id: str, campaign_id: str, authenticated_subject: str
) -> bool:
    """Fail closed unless the Keycloak subject has an active, synced membership."""
    try:
        with STORE.connect() as db:
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
                     AND m.sync_status='SYNCED' AND m.effective_until IS NULL
                   LIMIT 1""",
                (agent_id, campaign_id, tenant_id, tenant_id, tenant_id,
                 authenticated_subject, True),
            ).fetchone()
        return bool(row)
    except Exception:
        return False


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
        if urlparse(self.path).path == "/healthz":
            return self._json(200, {"status": "ok"})
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
        if not tenant or not client or not subject:
            return self._json(403, {"error": "authenticated_identity_required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 8192:
                raise ValueError("invalid_body")
            value = json.loads(self.rfile.read(length))
            agent_id = str(value["agent_id"]).strip()
            campaign_id = str(value["campaign_id"]).strip()
            if not agent_id or not campaign_id:
                raise ValueError("invalid_identity")
            if not authorized_agent_membership(tenant, agent_id, campaign_id, subject):
                return self._json(403, {"error": "active_agent_membership_required"})
            token, expires = issue_token(tenant, agent_id, campaign_id, client)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            return self._json(422, {"error": str(exc)})
        return self._json(201, {
            "token": token,
            "expires_at": expires,
            "websocket_url": "wss://api.codestra.co/ws/agent",
            "subprotocols": ["codestra-agent-v1", "session.<token>"],
        })


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
    async for raw in connection:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            await connection.close(code=4400, reason="invalid_json")
            return
        if value.get("type") != "ping":
            await connection.close(code=4403, reason="client_message_not_allowed")
            return
        await connection.send(json.dumps({"type": "pong", "at": int(time.time())}))


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
