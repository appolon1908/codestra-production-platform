from __future__ import annotations

import hashlib
import hmac
import json
import time

from odoo import http
from odoo.http import request

PREFIX = "CODESTRA-INTEGRATION-TEST-"


class CodestraMiddlewareBridge(http.Controller):
    def _json(self, status, value):
        return request.make_json_response(value, status=status)

    def _body(self):
        raw = request.httprequest.get_data()
        if len(raw) > 131072:
            return None, self._json(413, {"error": "body_too_large"})
        if not raw:
            return {}, None
        try:
            value = json.loads(raw)
        except ValueError:
            return None, self._json(422, {"error": "invalid_json"})
        if not isinstance(value, dict):
            return None, self._json(422, {"error": "object_required"})
        return value, None

    def _authenticate(self, body, tenant_allowlist_parameter=None):
        headers = request.httprequest.headers
        timestamp = headers.get("X-Codestra-Timestamp", "")
        event_id = headers.get("X-Codestra-Event-ID", "")
        supplied = headers.get("X-Codestra-Signature", "").removeprefix("sha256=")
        tenant = headers.get("X-Tenant-ID", "")
        correlation = headers.get("X-Correlation-ID", "")
        idempotency = headers.get("Idempotency-Key", "")
        params = request.env["ir.config_parameter"].sudo()
        expected_tenant = params.get_param("codestra.middleware.tenant_id")
        secret = params.get_param("codestra.middleware.inbound_hmac_secret")
        try:
            fresh = abs(int(time.time()) - int(timestamp)) <= 300
        except (TypeError, ValueError):
            fresh = False
        if not all((timestamp, event_id, supplied, tenant, correlation, idempotency)):
            return None, self._json(401, {"error": "missing_authentication"})
        if not fresh:
            return None, self._json(401, {"error": "expired_timestamp"})
        allowed_tenants = {expected_tenant} if expected_tenant else set()
        if tenant_allowlist_parameter:
            allowed_tenants.update(item.strip() for item in (params.get_param(tenant_allowlist_parameter) or "").split(",") if item.strip())
        if not any(hmac.compare_digest(tenant, item) for item in allowed_tenants):
            return None, self._json(403, {"error": "tenant_rejected"})
        canonical = b"\n".join((
            timestamp.encode(), event_id.encode(), request.httprequest.method.encode(),
            request.httprequest.path.encode(), body,
        ))
        expected = hmac.new((secret or "").encode(), canonical, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, supplied):
            return None, self._json(401, {"error": "invalid_signature"})
        user_id = int(params.get_param("codestra.middleware.service_user_id", "0"))
        user = request.env["res.users"].sudo().browse(user_id).exists()
        group = request.env.ref("codestra_middleware_bridge.group_codestra_middleware_bridge")
        if not user or group not in user.group_ids or not user.active:
            return None, self._json(403, {"error": "service_identity_rejected"})
        return {
            "event_id": event_id, "tenant_id": tenant,
            "correlation_id": correlation, "idempotency_key": idempotency,
            "request_hash": hashlib.sha256(body).hexdigest(), "user": user,
        }, None

    def _begin(self, operation, allow_event_replay=False, tenant_allowlist_parameter=None):
        body = request.httprequest.get_data()
        auth, error = self._authenticate(body, tenant_allowlist_parameter)
        if error:
            return None, None, error
        evidence = request.env["codestra.middleware.request"].with_user(auth["user"])
        replay = evidence.search([("event_id", "=", auth["event_id"])], limit=1)
        if replay:
            if allow_event_replay and replay.request_hash == auth["request_hash"] and replay.operation == operation:
                value = json.loads(replay.response_json)
                value["duplicate"] = True
                return None, None, self._json(200, value)
            return None, None, self._json(409, {"error": "replayed_event_id"})
        prior = evidence.search([
            ("tenant_id", "=", auth["tenant_id"]),
            ("idempotency_key", "=", auth["idempotency_key"]),
        ], limit=1)
        if prior:
            if prior.request_hash != auth["request_hash"] or prior.operation != operation:
                return None, None, self._json(409, {"error": "idempotency_conflict"})
            value = json.loads(prior.response_json)
            value["duplicate"] = True
            return None, None, self._json(200, value)
        payload, error = self._body()
        return auth, payload, error

    def _complete(self, auth, operation, value, partner=None, status=200):
        event_model = request.env["codestra.integration.event"].with_user(auth["user"])
        event = event_model.register_event(
            "middleware.odoo." + operation, "middleware", "odoo",
            {"synthetic_test": True, "partner_id": partner.id if partner else None},
            correlation_id=auth["correlation_id"],
            idempotency_key="middleware:%s:%s" % (operation, auth["idempotency_key"]),
        )
        request.env["codestra.integration.audit"].with_user(auth["user"])._append(
            event, "middleware." + operation, "success",
            {"partner_id": partner.id if partner else None, "tenant_id": auth["tenant_id"]},
        )
        value.update({"correlation_id": auth["correlation_id"], "duplicate": False})
        request.env["codestra.middleware.request"].with_user(auth["user"]).create({
            "event_id": auth["event_id"], "idempotency_key": auth["idempotency_key"],
            "request_hash": auth["request_hash"], "operation": operation,
            "correlation_id": auth["correlation_id"], "tenant_id": auth["tenant_id"],
            "response_json": json.dumps(value, sort_keys=True),
            "partner_id": partner.id if partner else False,
        })
        return self._json(status, value)

    def _partner(self, auth, partner_id):
        partner = request.env["res.partner"].with_user(auth["user"]).browse(partner_id).exists()
        if not partner or not (partner.name or "").startswith(PREFIX):
            return None
        return partner

    @http.route("/codestra/middleware/v1/email-events", type="http", auth="none", methods=["POST"], csrf=False)
    def email_event(self):
        auth, payload, error = self._begin("email.status", allow_event_replay=True, tenant_allowlist_parameter="codestra.middleware.email_tenant_ids")
        if error: return error
        status_by_type = {
            "klyrow.email.delivered": "delivered",
            "klyrow.email.bounced": "bounced",
            "klyrow.email.deferred": "deferred",
        }
        event_type = str(payload.get("event_type", ""))
        status = status_by_type.get(event_type)
        detail = payload.get("payload") or {}
        message_id = str(detail.get("message_id", ""))
        occurred_at = payload.get("occurred_at") or detail.get("timestamp")
        if not status or not message_id or not occurred_at:
            return self._json(422, {"error": "invalid_email_status_event"})
        occurred_at = str(occurred_at).replace("T", " ").removesuffix("Z").split(".", 1)[0]
        record = request.env["codestra.email.delivery.status"].with_user(auth["user"]).create({
            "event_id": auth["event_id"], "correlation_id": auth["correlation_id"],
            "message_id": message_id, "tenant_id": auth["tenant_id"],
            "customer_id": payload.get("customer_id"), "provider": "klyrow",
            "event_type": event_type, "status": status, "occurred_at": occurred_at,
        })
        return self._complete(auth, "email.status", {
            "record_id": record.id, "model": record._name, "status": record.status,
            "event_id": record.event_id, "message_id": record.message_id,
        }, status=201)

    @http.route("/codestra/middleware/v1/contacts", type="http", auth="none", methods=["POST"], csrf=False)
    def create_contact(self):
        auth, payload, error = self._begin("contact.create")
        if error: return error
        name = str(payload.get("name", ""))
        external_id = str(payload.get("external_id", ""))
        if not name.startswith(PREFIX) or not external_id.startswith(PREFIX):
            return self._json(422, {"error": "synthetic_tag_required"})
        partner = request.env["res.partner"].with_user(auth["user"]).create({
            "name": name, "email": payload.get("email"), "phone": payload.get("phone"),
            "codestra_integration_external_id": external_id,
            "codestra_integration_status": "test",
            "comment": "Synthetic middleware connectivity record; safe to archive.",
        })
        return self._complete(auth, "contact.create", self._contact_value(partner), partner, 201)

    @http.route("/codestra/middleware/v1/contacts/<int:partner_id>", type="http", auth="none", methods=["GET", "PATCH"], csrf=False)
    def contact(self, partner_id):
        operation = "contact.read" if request.httprequest.method == "GET" else "contact.update"
        auth, payload, error = self._begin(operation)
        if error: return error
        partner = self._partner(auth, partner_id)
        if not partner: return self._json(404, {"error": "synthetic_contact_not_found"})
        if operation == "contact.update":
            values = {key: payload[key] for key in ("email", "phone") if key in payload}
            if "name" in payload:
                if not str(payload["name"]).startswith(PREFIX):
                    return self._json(422, {"error": "synthetic_tag_required"})
                values["name"] = payload["name"]
            partner.write(values)
        return self._complete(auth, operation, self._contact_value(partner), partner)

    @http.route("/codestra/middleware/v1/contacts/<int:partner_id>/activities", type="http", auth="none", methods=["POST"], csrf=False)
    def activity(self, partner_id):
        auth, payload, error = self._begin("activity.create")
        if error: return error
        partner = self._partner(auth, partner_id)
        if not partner: return self._json(404, {"error": "synthetic_contact_not_found"})
        summary = str(payload.get("summary", ""))
        if not summary.startswith(PREFIX):
            return self._json(422, {"error": "synthetic_tag_required"})
        activity = request.env["mail.activity"].with_user(auth["user"]).create({
            "activity_type_id": request.env.ref("mail.mail_activity_data_todo").id,
            "summary": summary, "note": payload.get("note", "Synthetic connectivity activity"),
            "res_model_id": request.env["ir.model"]._get_id("res.partner"),
            "res_id": partner.id, "user_id": auth["user"].id,
        })
        return self._complete(auth, "activity.create", {"activity_id": activity.id, "partner_id": partner.id}, partner, 201)

    @http.route("/codestra/middleware/v1/contacts/<int:partner_id>/status", type="http", auth="none", methods=["POST"], csrf=False)
    def status(self, partner_id):
        auth, payload, error = self._begin("contact.status")
        if error: return error
        partner = self._partner(auth, partner_id)
        if not partner: return self._json(404, {"error": "synthetic_contact_not_found"})
        value = payload.get("status")
        if value not in {"test", "active", "inactive"}:
            return self._json(422, {"error": "invalid_status"})
        partner.write({"codestra_integration_status": value})
        return self._complete(auth, "contact.status", self._contact_value(partner), partner)

    @staticmethod
    def _contact_value(partner):
        return {
            "partner_id": partner.id, "external_id": partner.codestra_integration_external_id,
            "name": partner.name, "email": partner.email, "phone": partner.phone,
            "status": partner.codestra_integration_status,
        }
