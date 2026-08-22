from __future__ import annotations

import hmac
import hashlib
import json
import os
import uuid
import urllib.parse
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .core import ControlPlaneError, Store, credential_matches, validate_envelope, verify_signature


def verifier(name: str) -> str:
    file_name = os.getenv(f"{name}_SHA256_FILE", "")
    if not file_name:
        return ""
    with open(file_name, "r", encoding="utf-8") as handle:
        value = handle.read().strip().lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RuntimeError(f"invalid verifier for {name}")
    return value
from .database import IntegrityError
from .providers import ProviderError, crawler_action, submit_crawler
from .crm import ACTIVITY_FIELDS, CREATE_FIELDS, PATCH_FIELDS, CrmService, request_hash
from .forms import FormService, ORIGINS
from .mapping_registry import MappingRegistry

DB = os.getenv("CONTROL_PLANE_DB", "/data/control-plane.db")
STORE = Store(DB)
MAPPINGS = MappingRegistry(DB)
TTL = int(os.getenv("CONTROL_PLANE_HMAC_TTL", "300"))
MAX_BODY = int(os.getenv("CONTROL_PLANE_MAX_BODY", "524288"))


def identity(source: str) -> tuple[str, str]:
    prefix = source.upper()
    secret = os.getenv("N8N_MIDDLEWARE_HMAC_SECRET", "") if source == "n8n" else ""
    return os.getenv(f"{prefix}_MIDDLEWARE_API_KEY", ""), secret or os.getenv(f"{prefix}_WEBHOOK_SECRET", "")


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


def apply_provider_projection(store: Store, source: str, value: dict) -> None:
    try:
        store.apply_provider_event(source, value)
    except ControlPlaneError as exc:
        # Provider callbacks can describe messages created by Odoo rather than
        # by this control plane. Keep immutable event fan-out and skip only the
        # optional local projection when the originating message is absent.
        if str(exc) != "message_not_found":
            raise


class Handler(BaseHTTPRequestHandler):
    server_version = "CodestraControlPlane/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(json.dumps({"system": "control-plane", "client": self.client_address[0], "message": fmt % args}))

    def send_json(self, code: int, value: object, origin: str = "") -> None:
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw)))
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin); self.send_header("Vary", "Origin")
        self.end_headers(); self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin not in ORIGINS or not urlparse(self.path).path.startswith("/v1/forms/"):
            return self.send_json(403, {"error": "origin_denied"})
        self.send_response(204); self.send_header("Access-Control-Allow-Origin", origin); self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key, X-Correlation-ID")
        self.send_header("Access-Control-Max-Age", "600"); self.end_headers()

    def body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ControlPlaneError("invalid_body_size")
        return self.rfile.read(length)

    def auth_operator(self, roles: set[str]) -> tuple[str, str, str | None] | None:
        proxy_cidrs=[]
        try:
            proxy_cidrs=[ipaddress.ip_network(value.strip()) for value in os.getenv("CONTROL_PLANE_TRUSTED_PROXY_CIDRS","").split(",") if value.strip()]
            peer=ipaddress.ip_address(self.client_address[0])
        except ValueError:
            proxy_cidrs=[]; peer=None
        client=self.headers.get("X-Authenticated-Client","")
        tenant=self.headers.get("X-Authenticated-Tenant","")
        if peer is not None and client and tenant and any(peer in network for network in proxy_cidrs):
            return (client,"tenant_admin",tenant)
        raw = self.headers.get("Authorization", "").removeprefix("Bearer ")
        value = operator(raw)
        if not value or value[1] not in roles:
            self.send_json(403, {"error": "forbidden"}); return None
        return value

    def crm_customer(self):
        expected = verifier("CRM_KONG_SHARED_SECRET")
        previous = verifier("CRM_KONG_SHARED_SECRET_PREVIOUS")
        supplied = self.headers.get("X-Codestra-Crm-Gateway-Secret", "")
        consumer_id = self.headers.get("X-Consumer-ID", "")
        custom_id = self.headers.get("X-Consumer-Custom-ID", "")
        supplied_digest = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
        secret_valid = bool(expected) and hmac.compare_digest(expected, supplied_digest)
        if previous:
            secret_valid = secret_valid or hmac.compare_digest(previous, supplied_digest)
        if not secret_valid or not consumer_id or not custom_id:
            self.send_json(401, {"error": "unauthorized"}); return None
        try: return STORE.crm_customer(consumer_id, custom_id)
        except ControlPlaneError as exc:
            self.send_json(403, {"error": str(exc)}); return None

    def crm_error(self, exc: Exception, correlation: str) -> None:
        message = str(exc)
        code = 409 if message == "idempotency_conflict" else 422 if message.startswith("unsupported_fields") else 503 if message in {"odoo_unavailable", "crm_odoo_not_configured"} else 404 if message.endswith("not_found") else 403
        self.send_json(code, {"error": message.split(":", 1)[0], "correlation_id": correlation})

    def crm_get(self, parsed) -> bool:
        if not parsed.path.startswith("/v1/crm/"): return False
        customer = self.crm_customer()
        if not customer: return True
        crm = CrmService(STORE); correlation = crm.correlation(self.headers)
        if parsed.path == "/v1/crm/account":
            STORE.crm_audit(customer["customer_id"], "account.read", None, [], "success", 200, correlation)
            self.send_json(200, {**crm.account(customer), "correlation_id": correlation}); return True
        prefix = "/v1/crm/leads/"
        if not parsed.path.startswith(prefix): self.send_json(404, {"error": "not_found"}); return True
        external_id = urllib.parse.unquote(parsed.path[len(prefix):])
        try:
            STORE.crm_object(customer["customer_id"], external_id)
            status, result = crm.call(customer, "GET", "/leads/" + urllib.parse.quote(external_id, safe=""), {}, correlation, "read:" + correlation)
        except ControlPlaneError as exc:
            STORE.crm_audit(customer["customer_id"], "lead.read", external_id, [], "denied", 404, correlation)
            self.crm_error(exc, correlation); return True
        STORE.crm_audit(customer["customer_id"], "lead.read", external_id, [], "success" if status < 300 else "failed", status, correlation)
        result["correlation_id"] = correlation; self.send_json(status, result); return True

    def crm_mutation(self, method: str) -> bool:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/v1/crm/"): return False
        customer = self.crm_customer()
        if not customer: return True
        correlation = CrmService.correlation(self.headers)
        try: payload = json.loads(self.body())
        except (json.JSONDecodeError, ControlPlaneError): self.send_json(422, {"error": "invalid_json", "correlation_id": correlation}); return True
        if not isinstance(payload, dict): self.send_json(422, {"error": "object_required", "correlation_id": correlation}); return True
        crm = CrmService(STORE); external_id = None; operation = ""; allowed: set[str]
        if method == "POST" and parsed.path == "/v1/crm/leads":
            operation, allowed = "lead.create", CREATE_FIELDS; external_id = str(payload.get("customer_reference", ""))
            if not external_id or not payload.get("name"):
                self.send_json(422, {"error": "missing_required_fields", "correlation_id": correlation}); return True
        elif method == "POST" and parsed.path == "/v1/crm/activities":
            operation, allowed = "activity.create", ACTIVITY_FIELDS; external_id = str(payload.get("lead_external_id", ""))
        elif method == "PATCH" and parsed.path.startswith("/v1/crm/leads/"):
            operation, allowed = "lead.update", PATCH_FIELDS; external_id = urllib.parse.unquote(parsed.path[len("/v1/crm/leads/"):])
        else: self.send_json(404, {"error": "not_found"}); return True
        key = self.headers.get("Idempotency-Key", "")
        if not key: self.send_json(422, {"error": "idempotency_key_required", "correlation_id": correlation}); return True
        digest = request_hash(payload)
        try:
            crm.validate_fields(payload, allowed)
            prior = STORE.crm_idempotency(customer["customer_id"], operation, key, digest)
            if prior:
                result, status = prior; result["duplicate"] = True; result["correlation_id"] = correlation
                self.send_json(status, result); return True
            if operation != "lead.create": STORE.crm_object(customer["customer_id"], external_id)
            outbound = dict(payload)
            if operation == "lead.create":
                outbound.update({"external_id": external_id, "middleware_id": str(uuid.uuid4())})
                path = "/leads"
            elif operation == "lead.update": path = "/leads/" + urllib.parse.quote(external_id, safe="")
            else:
                outbound["middleware_id"] = str(uuid.uuid4()); path = "/activities"
            status, result = crm.call(customer, method, path, outbound, correlation, key)
            if status >= 300:
                STORE.crm_audit(customer["customer_id"], operation, external_id, list(payload), "failed", status, correlation)
                result["correlation_id"] = correlation; self.send_json(status, result); return True
            if operation == "lead.create": STORE.crm_save_object(customer["customer_id"], external_id, outbound["middleware_id"], "crm.lead")
            elif operation == "activity.create":
                STORE.crm_save_object(customer["customer_id"], result["external_id"], outbound["middleware_id"], "mail.activity")
            result["duplicate"] = False; result["correlation_id"] = correlation
            STORE.crm_save_idempotency(customer["customer_id"], operation, key, digest, result, status)
            STORE.crm_audit(customer["customer_id"], operation, external_id, list(payload), "success", status, correlation)
            crm.emit(customer, {"lead.create":"crm.lead.created", "lead.update":"crm.lead.updated", "activity.create":"crm.activity.created"}[operation], external_id, correlation)
            self.send_json(status, result); return True
        except (ControlPlaneError, IntegrityError) as exc:
            STORE.crm_audit(customer["customer_id"], operation, external_id, list(payload), "denied", 409 if "idempotency" in str(exc) else 422, correlation)
            self.crm_error(exc, correlation); return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/health", "/v1/health", "/livez"}:
            return self.send_json(200, {"status": "alive"})
        if parsed.path in {"/ready", "/readyz"}:
            try: STORE.list_events(None, limit=1)
            except Exception: return self.send_json(503, {"status": "not_ready"})
            return self.send_json(200, {"status": "ready", "outbound_safe_mode": os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED", "false") != "true"})
        if parsed.path == "/v1/ready":
            try: STORE.list_messages("__readiness__", limit=1)
            except Exception: return self.send_json(503, {"status": "not_ready"})
            production_enabled=os.getenv("CONTROL_PLANE_OUTBOUND_ENABLED","false")=="true" and os.getenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED","false")=="true" and os.getenv("TELNEXA_MODE","simulator")=="production" and os.getenv("KLYROW_MODE","test")=="production"
            return self.send_json(200, {"status":"ready","providers":{"telnexa":os.getenv("TELNEXA_MODE","simulator"),"klyrow":os.getenv("KLYROW_MODE","test")},"production_delivery_enabled":production_enabled})
        if parsed.path == "/metrics":
            raw = (STORE.metrics()+MAPPINGS.metrics()).encode(); self.send_response(200); self.send_header("Content-Type", "text/plain; version=0.0.4"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); return self.wfile.write(raw)
        if self.crm_get(parsed): return
        op = self.auth_operator({"platform_admin", "operations", "support", "auditor", "tenant_admin"})
        if not op: return
        query = parse_qs(parsed.query); tenant = op[2] or query.get("tenant_id", [None])[0]
        if parsed.path.startswith("/api/v1/control/jobs/"):
            try: job = MAPPINGS.get_job(parsed.path.rsplit("/", 1)[-1])
            except ControlPlaneError as exc: return self.send_json(404, {"error": str(exc)})
            if tenant and job["tenant_id"] != tenant: return self.send_json(404, {"error": "not_found"})
            return self.send_json(200, job)
        if parsed.path in {"/v1/messages", "/api/v1/messages"}:
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            return self.send_json(200,{"items":STORE.list_messages(tenant,query.get("channel",[None])[0],query.get("status",[None])[0])})
        if parsed.path.startswith(("/v1/messages/", "/api/v1/messages/")):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            parts=parsed.path.strip("/").split("/"); message_id=parts[2] if parts[0]=="v1" else parts[3]
            event_request=parts[-1]=="events"
            try: result={"items":STORE.message_events(message_id,tenant)} if event_request else STORE.get_message(message_id,tenant)
            except ControlPlaneError as exc: return self.send_json(404,{"error":str(exc)})
            return self.send_json(200,result)
        if parsed.path.startswith("/v1/customers/") and parsed.path.endswith("/preferences"):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            return self.send_json(200,STORE.get_preferences(tenant,parsed.path.split("/")[3]))
        if parsed.path.startswith("/v1/crawler/jobs/"):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            parts=parsed.path.strip("/").split("/"); job_id=parts[3]
            try:
                job=STORE.get_crawler_job(job_id,tenant)
                if len(parts)>4 and parts[4]=="results":
                    result=crawler_action("results",job); items=STORE.save_crawler_results(job_id,tenant,list(result.get("items") or []))
                    STORE.transition_crawler_job(job_id,tenant,str(result.get("status") or "completed"))
                    return self.send_json(200,{"job_id":job_id,"items":items})
                result=crawler_action("status",job)
                if result.get("status"): job=STORE.transition_crawler_job(job_id,tenant,str(result["status"]))
                return self.send_json(200,job)
            except ControlPlaneError as exc: return self.send_json(404,{"error":str(exc)})
            except ProviderError as exc: return self.send_json(503,{"error":str(exc)})
        if parsed.path == "/api/v1/ops/summary": return self.send_json(200, STORE.summary(tenant))
        if parsed.path == "/api/v1/ops/events": return self.send_json(200, {"items": STORE.list_events(tenant, query.get("state", [None])[0])})
        if parsed.path.startswith("/api/v1/ops/correlations/"): return self.send_json(200, {"items": STORE.correlation(parsed.path.rsplit("/", 1)[-1], tenant)})
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/v1/forms/"):
            origin = self.headers.get("Origin", "")
            try:
                raw = self.body(); value = json.loads(raw)
                if not isinstance(value, dict): raise ControlPlaneError("object_required")
                status, result = FormService(STORE).submit(parsed.path.rsplit("/", 1)[-1], value, self.headers, len(raw))
                return self.send_json(status, result, origin)
            except json.JSONDecodeError: return self.send_json(422, {"error": "invalid_json"}, origin)
            except ControlPlaneError as exc:
                message = str(exc); code = 404 if message == "form_not_found" else 413 if message == "body_too_large" else 409 if message == "idempotency_conflict" else 403 if message in {"origin_denied", "bot_rejected"} else 422
                return self.send_json(code, {"error": message.split(":", 1)[0]}, origin)
        if parsed.path.startswith("/v1/crm/"):
            self.crm_mutation("POST"); return
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
                # A signed webhook event ID is a nonce. Exact transport retries
                # must use a fresh event ID and retain the original idempotency
                # key; reusing the signed ID is a replay attack for every
                # external producer, not only Odoo.
                result = STORE.ingest(
                    value,
                    reject_event_replay=source in {"odoo", "telnexa", "klyrow"},
                )
                if not result.duplicate and source in {"telnexa","klyrow"} and value.get("payload",{}).get("message_id") and not value.get("metadata", {}).get("sms_postgres_authority"):
                    apply_provider_projection(STORE, source, value)
            except (ControlPlaneError, json.JSONDecodeError) as exc:
                code = 409 if str(exc) in {"idempotency_conflict", "replayed_event_id"} else 401 if "signature" in str(exc) or "timestamp" in str(exc) else 422
                return self.send_json(code, {"error": str(exc)})
            return self.send_json(200 if result.duplicate else 202, result.__dict__)
        op = self.auth_operator({"platform_admin", "operations", "support", "tenant_admin"})
        if not op: return
        try: value = json.loads(body)
        except json.JSONDecodeError: return self.send_json(422, {"error": "invalid_json"})
        tenant = op[2] or value.get("tenant_id")
        if parsed.path == "/api/v1/control/campaigns":
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            value["tenant_id"] = tenant
            value.setdefault("idempotency_key", self.headers.get("Idempotency-Key"))
            value.setdefault("correlation_id", self.headers.get("X-Correlation-ID"))
            if not value.get("idempotency_key"): return self.send_json(422,{"error":"idempotency_key_required"})
            try: result, duplicate = MAPPINGS.create_campaign(value, actor=op[0])
            except ControlPlaneError as exc:
                return self.send_json(409 if str(exc) in {"idempotency_conflict","mapping_collision"} else 422,{"error":str(exc)})
            result["duplicate"] = duplicate
            return self.send_json(200 if duplicate else 202,result)
        if parsed.path.startswith("/api/v1/results/jobs/"):
            job_id = parsed.path.rsplit("/",1)[-1]
            try: result = MAPPINGS.record_result(job_id,value)
            except ControlPlaneError as exc: return self.send_json(409 if str(exc)=="stale_version" else 422,{"error":str(exc)})
            return self.send_json(202,result)
        if parsed.path == "/api/v1/reconciliation/run":
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            try:
                result=MAPPINGS.reconcile(tenant,value["entity_type"],value["entity_id"],value["target_system"],value["desired"],value["actual"],value["drift_code"],correlation_id=value.get("correlation_id"))
            except (KeyError,ControlPlaneError) as exc: return self.send_json(422,{"error":str(exc)})
            return self.send_json(200,result)
        if parsed.path in {"/v1/messages/sms","/v1/messages/email","/api/v1/control/messages"}:
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            value["tenant_id"]=tenant
            if parsed.path != "/api/v1/control/messages": value["channel"]=parsed.path.rsplit("/",1)[-1]
            value.setdefault("request_id",self.headers.get("X-Request-Id")); value.setdefault("correlation_id",self.headers.get("X-Correlation-Id")); value.setdefault("idempotency_key",self.headers.get("Idempotency-Key"))
            try: message,duplicate=STORE.create_message(value)
            except ControlPlaneError as exc:
                code=409 if str(exc)=="idempotency_conflict" else 403 if str(exc) in {"consent_required","destination_suppressed"} else 422
                return self.send_json(code,{"error":str(exc)})
            STORE.audit(op[0],op[1],"message.created","message",message["message_id"],tenant,message["correlation_id"],{"channel":message["channel"],"duplicate":duplicate})
            return self.send_json(200 if duplicate else 202,message)
        if parsed.path.startswith("/api/v1/control/messages/") and parsed.path.endswith("/dispatch"):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            message_id=parsed.path.split("/")[5]
            try:
                message=STORE.get_message(message_id,tenant)
                if message["status"] not in {"queued","failed","rejected","deferred"}: raise ControlPlaneError("message_not_dispatchable")
                if message["status"] != "queued": message=STORE.retry_message(message_id,tenant)
            except ControlPlaneError as exc: return self.send_json(409 if "not_dispatchable" in str(exc) else 404,{"error":str(exc)})
            STORE.audit(op[0],op[1],"message.dispatch.requested","message",message_id,tenant,message["correlation_id"])
            return self.send_json(202,message)
        if parsed.path.startswith("/api/v1/results/messages/"):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            message_id=parsed.path.rsplit("/",1)[-1]
            try:
                changed=STORE.transition_message(message_id,tenant,str(value["status"]).lower(),str(value.get("provider_status") or value["status"]),
                  event_id=str(value.get("event_id") or uuid.uuid4()),provider_message_id=value.get("provider_message_id"),error_code=value.get("error_code"),payload=value)
                message=STORE.get_message(message_id,tenant)
            except (KeyError,ControlPlaneError) as exc: return self.send_json(409 if str(exc)=="idempotency_conflict" else 422,{"error":str(exc)})
            return self.send_json(200 if not changed else 202,message)
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
        if parsed.path.startswith("/v1/crawler/jobs/") and parsed.path.endswith(("/cancel","/retry")):
            if not tenant: return self.send_json(422,{"error":"tenant_required"})
            parts=parsed.path.strip("/").split("/"); job_id=parts[3]; action=parts[4]
            try:
                job=STORE.get_crawler_job(job_id,tenant); result=crawler_action(action,job)
                job=STORE.transition_crawler_job(job_id,tenant,str(result.get("status") or ("cancelled" if action=="cancel" else "accepted")))
            except ControlPlaneError as exc: return self.send_json(404,{"error":str(exc)})
            except ProviderError as exc: return self.send_json(503,{"error":str(exc)})
            STORE.audit(op[0],op[1],"crawler.job."+action,"crawler_job",job_id,tenant,job["correlation_id"])
            return self.send_json(200,job)
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

    def do_PATCH(self) -> None:
        if self.crm_mutation("PATCH"): return
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
