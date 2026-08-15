from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .core import ControlPlaneError, Store, validate_envelope, verify_signature

DB = os.getenv("CONTROL_PLANE_DB", "/data/control-plane.db")
STORE = Store(DB)
TTL = int(os.getenv("CONTROL_PLANE_HMAC_TTL", "300"))
MAX_BODY = int(os.getenv("CONTROL_PLANE_MAX_BODY", "524288"))


def identity(source: str) -> tuple[str, str]:
    prefix = source.upper()
    return os.getenv(f"{prefix}_MIDDLEWARE_API_KEY", ""), os.getenv(f"{prefix}_WEBHOOK_SECRET", "")


def operator(token: str) -> tuple[str, str, str | None] | None:
    for role in ("platform_admin", "operations", "support", "auditor"):
        expected = os.getenv("CONTROL_PLANE_" + role.upper() + "_TOKEN", "")
        if expected and hmac.compare_digest(token, expected):
            return (role, role, None)
    tenant_token = os.getenv("CONTROL_PLANE_TENANT_ADMIN_TOKEN", "")
    tenant = os.getenv("CONTROL_PLANE_TENANT_ADMIN_TENANT", "")
    if tenant_token and tenant and hmac.compare_digest(token, tenant_token):
        return ("tenant_admin", "tenant_admin", tenant)
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "CodestraControlPlane/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(json.dumps({"system": "control-plane", "client": self.client_address[0], "message": fmt % args}))

    def send_json(self, code: int, value: object) -> None:
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ControlPlaneError("invalid_body_size")
        return self.rfile.read(length)

    def auth_operator(self, roles: set[str]) -> tuple[str, str, str | None] | None:
        raw = self.headers.get("Authorization", "").removeprefix("Bearer ")
        value = operator(raw)
        if not value or value[1] not in roles:
            self.send_json(403, {"error": "forbidden"}); return None
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health": return self.send_json(200, {"status": "ok"})
        if parsed.path == "/ready":
            try: STORE.list_events(None, limit=1)
            except Exception: return self.send_json(503, {"status": "not_ready"})
            return self.send_json(200, {"status": "ready", "outbound_safe_mode": os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true"})
        if parsed.path == "/metrics":
            raw = STORE.metrics().encode(); self.send_response(200); self.send_header("Content-Type", "text/plain; version=0.0.4"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); return self.wfile.write(raw)
        op = self.auth_operator({"platform_admin", "operations", "support", "auditor", "tenant_admin"})
        if not op: return
        query = parse_qs(parsed.query); tenant = op[2] or query.get("tenant_id", [None])[0]
        if parsed.path == "/api/v1/ops/summary": return self.send_json(200, STORE.summary(tenant))
        if parsed.path == "/api/v1/ops/events": return self.send_json(200, {"items": STORE.list_events(tenant, query.get("state", [None])[0])})
        if parsed.path.startswith("/api/v1/ops/correlations/"): return self.send_json(200, {"items": STORE.correlation(parsed.path.rsplit("/", 1)[-1], tenant)})
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try: body = self.body()
        except ControlPlaneError as exc: return self.send_json(413, {"error": str(exc)})
        if parsed.path.startswith("/api/v1/events/"):
            source = parsed.path.rsplit("/", 1)[-1]
            if source not in {"kyqra", "telnexa", "klyrow", "n8n", "odoo"}: return self.send_json(404, {"error": "unknown_source"})
            api_key, secret = identity(source); supplied = self.headers.get("Authorization", "")
            if not api_key or not hmac.compare_digest(supplied, "Bearer " + api_key): return self.send_json(401, {"error": "invalid_api_key"})
            event_id = self.headers.get("X-Event-Id", ""); timestamp = self.headers.get("X-Timestamp", ""); signature = self.headers.get("X-Signature", "")
            try:
                verify_signature(secret, timestamp, event_id, source, body, signature, TTL)
                value = validate_envelope(json.loads(body), source, event_id)
                result = STORE.ingest(value)
            except (ControlPlaneError, json.JSONDecodeError) as exc:
                code = 409 if str(exc) in {"idempotency_conflict"} else 401 if "signature" in str(exc) or "timestamp" in str(exc) else 422
                return self.send_json(code, {"error": str(exc)})
            return self.send_json(200 if result.duplicate else 202, result.__dict__)
        op = self.auth_operator({"platform_admin", "operations", "support", "tenant_admin"})
        if not op: return
        try: value = json.loads(body)
        except json.JSONDecodeError: return self.send_json(422, {"error": "invalid_json"})
        tenant = op[2] or value.get("tenant_id")
        if not tenant and parsed.path.startswith("/api/v1/preferences"): return self.send_json(422, {"error": "tenant_required"})
        if parsed.path == "/api/v1/preferences":
            try: STORE.set_preference(tenant, value["contact_id"], value["channel"], value["status"], value.get("source", "operator"), value.get("reason"))
            except (KeyError, ControlPlaneError) as exc: return self.send_json(422, {"error": str(exc)})
            STORE.audit(op[0], op[1], "preference.changed", "preference", value["contact_id"], tenant, self.headers.get("X-Correlation-Id")); return self.send_json(200, {"updated": True})
        if parsed.path == "/api/v1/preferences/check": return self.send_json(200, {"allowed": STORE.preference_allows(tenant, value["contact_id"], value["channel"])})
        if parsed.path.startswith("/api/v1/ops/events/") and parsed.path.endswith("/replay"):
            event_id = parsed.path.split("/")[-2]; changed = STORE.retry(event_id); STORE.audit(op[0], op[1], "event.replayed", "event", event_id, tenant, value.get("correlation_id")); return self.send_json(200 if changed else 409, {"queued": changed})
        if parsed.path.startswith("/api/v1/ops/integrations/") and parsed.path.endswith(("/pause", "/resume")):
            name = parsed.path.split("/")[-2]; paused = parsed.path.endswith("/pause"); changed = STORE.pause(name, paused); STORE.audit(op[0], op[1], "integration.paused" if paused else "integration.resumed", "integration", name, tenant, value.get("correlation_id")); return self.send_json(200 if changed else 404, {"paused": paused})
        self.send_json(404, {"error": "not_found"})


def main() -> None:
    ThreadingHTTPServer((os.getenv("CONTROL_PLANE_BIND", "127.0.0.1"), int(os.getenv("CONTROL_PLANE_PORT", "8096"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
