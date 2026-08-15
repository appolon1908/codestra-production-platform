from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .core import ControlPlaneError, Store, credential_matches, validate_envelope, verify_signature
from .providers import ProviderError, submit_crawler

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
        if parsed.path == "/v1/health": return self.send_json(200, {"status": "ok"})
        if parsed.path == "/ready":
            try: STORE.list_events(None, limit=1)
            except Exception: return self.send_json(503, {"status": "not_ready"})
            return self.send_json(200, {"status": "ready", "outbound_safe_mode": os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true"})
        if parsed.path == "/v1/ready":
            try: STORE.list_messages("__readiness__", limit=1)
            except Exception: return self.send_json(503, {"status": "not_ready"})
            production_enabled=os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED","false")=="true" and os.getenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED","false")=="true" and os.getenv("TELNEXA_MODE","simulator")=="production" and os.getenv("KLYROW_MODE","test")=="production"
            return self.send_json(200, {"status":"ready","providers":{"telnexa":os.getenv("TELNEXA_MODE","simulator"),"klyrow":os.getenv("KLYROW_MODE","test")},"production_delivery_enabled":production_enabled})
        if parsed.path == "/metrics":
            raw = STORE.metrics().encode(); self.send_response(200); self.send_header("Content-Type", "text/plain; version=0.0.4"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); return self.wfile.write(raw)
        op = self.auth_operator({"platform_admin", "operations", "support", "auditor", "tenant_admin"})
        if not op: return
        query = parse_qs(parsed.query); tenant = op[2] or query.get("tenant_id", [None])[0]
        if parsed.path == "/v1/messages":
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            return self.send_json(200,{"items":STORE.list_messages(tenant,query.get("channel",[None])[0],query.get("status",[None])[0])})
        if parsed.path.startswith("/v1/messages/"):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            parts=parsed.path.strip("/").split("/"); message_id=parts[2]
            try: result={"items":STORE.message_events(message_id,tenant)} if len(parts)>3 and parts[3]=="events" else STORE.get_message(message_id,tenant)
            except ControlPlaneError as exc: return self.send_json(404,{"error":str(exc)})
            return self.send_json(200,result)
        if parsed.path.startswith("/v1/customers/") and parsed.path.endswith("/preferences"):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            return self.send_json(200,STORE.get_preferences(tenant,parsed.path.split("/")[3]))
        if parsed.path.startswith("/v1/crawler/jobs/"):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            try: return self.send_json(200, STORE.get_crawler_job(parsed.path.rsplit("/",1)[-1],tenant))
            except ControlPlaneError as exc: return self.send_json(404,{"error":str(exc)})
        if parsed.path == "/api/v1/ops/summary": return self.send_json(200, STORE.summary(tenant))
        if parsed.path == "/api/v1/ops/events": return self.send_json(200, {"items": STORE.list_events(tenant, query.get("state", [None])[0])})
        if parsed.path.startswith("/api/v1/ops/correlations/"): return self.send_json(200, {"items": STORE.correlation(parsed.path.rsplit("/", 1)[-1], tenant)})
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try: body = self.body()
        except ControlPlaneError as exc: return self.send_json(413, {"error": str(exc)})
        if parsed.path.startswith("/api/v1/events/") or parsed.path == "/v1/events":
            source = parsed.path.rsplit("/", 1)[-1] if parsed.path != "/v1/events" else self.headers.get("X-Event-Source", "")
            if source not in {"kyqra", "telnexa", "klyrow", "n8n", "odoo"}: return self.send_json(404, {"error": "unknown_source"})
            api_key, secret = identity(source); supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            digest = os.getenv(f"{source.upper()}_MIDDLEWARE_API_KEY_SHA256", "")
            if not credential_matches(supplied, api_key, digest): return self.send_json(401, {"error": "invalid_api_key"})
            event_id = self.headers.get("X-Event-Id", ""); timestamp = self.headers.get("X-Timestamp", ""); signature = self.headers.get("X-Signature", "")
            try:
                verify_signature(secret, timestamp, event_id, source, body, signature, TTL)
                value = validate_envelope(json.loads(body), source, event_id)
                if source == "telnexa" and value["event_type"] == "telnexa.sms.received" and not value["payload"].get("message_id"):
                    inbound,_ = STORE.create_inbound_sms(value); value["payload"]["message_id"] = inbound["message_id"]
                # Odoo signs a unique immutable event ID. Reject its reuse
                # atomically; legitimate retries use a fresh event ID with the
                # same tenant-scoped idempotency key.
                result = STORE.ingest(value, reject_event_replay=source == "odoo")
                if not result.duplicate and source in {"telnexa","klyrow"} and value.get("payload",{}).get("message_id"):
                    STORE.apply_provider_event(source,value)
            except (ControlPlaneError, json.JSONDecodeError) as exc:
                code = 409 if str(exc) in {"idempotency_conflict", "replayed_event_id"} else 401 if "signature" in str(exc) or "timestamp" in str(exc) else 422
                return self.send_json(code, {"error": str(exc)})
            return self.send_json(200 if result.duplicate else 202, result.__dict__)
        op = self.auth_operator({"platform_admin", "operations", "support", "tenant_admin"})
        if not op: return
        try: value = json.loads(body)
        except json.JSONDecodeError: return self.send_json(422, {"error": "invalid_json"})
        tenant = op[2] or value.get("tenant_id")
        if parsed.path in {"/v1/messages/sms","/v1/messages/email"}:
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            value["tenant_id"]=tenant; value["channel"]=parsed.path.rsplit("/",1)[-1]
            value.setdefault("request_id",self.headers.get("X-Request-Id")); value.setdefault("correlation_id",self.headers.get("X-Correlation-Id")); value.setdefault("idempotency_key",self.headers.get("Idempotency-Key"))
            try: message,duplicate=STORE.create_message(value)
            except ControlPlaneError as exc:
                code=409 if str(exc)=="idempotency_conflict" else 403 if str(exc) in {"consent_required","destination_suppressed"} else 422
                return self.send_json(code,{"error":str(exc)})
            STORE.audit(op[0],op[1],"message.created","message",message["message_id"],tenant,message["correlation_id"],{"channel":message["channel"],"duplicate":duplicate})
            return self.send_json(200 if duplicate else 202,message)
        if parsed.path == "/v1/crawler/jobs":
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            value["tenant_id"]=tenant
            value.setdefault("correlation_id",self.headers.get("X-Correlation-Id"))
            value.setdefault("idempotency_key",self.headers.get("Idempotency-Key"))
            try:
                job,duplicate=STORE.create_crawler_job(value)
                if not duplicate:
                    result=submit_crawler(job); job=STORE.accept_crawler_job(job["job_id"],tenant,result.provider_message_id)
            except ControlPlaneError as exc: return self.send_json(409 if str(exc)=="idempotency_conflict" else 422,{"error":str(exc)})
            except ProviderError as exc: return self.send_json(503,{"error":str(exc)})
            STORE.audit(op[0],op[1],"crawler.job.created","crawler_job",job["job_id"],tenant,job["correlation_id"],{"duplicate":duplicate})
            return self.send_json(200 if duplicate else 202,job)
        if parsed.path.startswith("/v1/messages/") and parsed.path.endswith(("/cancel","/retry")):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            message_id=parsed.path.split("/")[3]
            try: message=STORE.cancel_message(message_id,tenant) if parsed.path.endswith("/cancel") else STORE.retry_message(message_id,tenant)
            except ControlPlaneError as exc: return self.send_json(409 if "not_" in str(exc) else 404,{"error":str(exc)})
            STORE.audit(op[0],op[1],"message.cancelled" if parsed.path.endswith("/cancel") else "message.retried","message",message_id,tenant,message["correlation_id"]); return self.send_json(200,message)
        if parsed.path.startswith("/v1/customers/") and parsed.path.endswith("/preferences"):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            customer=parsed.path.split("/")[3]
            try:
                for channel,pref in value.get("channels",{}).items(): STORE.set_preference(tenant,customer,channel,pref["status"],pref.get("source","operator"),pref.get("reason"))
            except (KeyError,ControlPlaneError) as exc: return self.send_json(422,{"error":str(exc)})
            STORE.audit(op[0],op[1],"preference.changed","preference",customer,tenant,self.headers.get("X-Correlation-Id")); return self.send_json(200,STORE.get_preferences(tenant,customer))
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

    def do_PUT(self) -> None:
        parsed=urlparse(self.path)
        if not (parsed.path.startswith("/v1/customers/") and parsed.path.endswith("/preferences")):
            return self.send_json(404,{"error":"not_found"})
        op=self.auth_operator({"platform_admin","operations","tenant_admin"})
        if not op: return
        try: value=json.loads(self.body())
        except (json.JSONDecodeError,ControlPlaneError) as exc: return self.send_json(422,{"error":str(exc)})
        tenant=op[2] or value.get("tenant_id"); customer=parsed.path.split("/")[3]
        if not tenant: return self.send_json(422,{"error":"tenant_required"})
        try:
            for channel,pref in value.get("channels",{}).items(): STORE.set_preference(tenant,customer,channel,pref["status"],pref.get("source","operator"),pref.get("reason"))
        except (KeyError,ControlPlaneError) as exc: return self.send_json(422,{"error":str(exc)})
        STORE.audit(op[0],op[1],"preference.changed","preference",customer,tenant,self.headers.get("X-Correlation-Id")); return self.send_json(200,STORE.get_preferences(tenant,customer))


def main() -> None:
    ThreadingHTTPServer((os.getenv("CONTROL_PLANE_BIND", "127.0.0.1"), int(os.getenv("CONTROL_PLANE_PORT", "8096"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
