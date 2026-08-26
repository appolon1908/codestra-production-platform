from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .call_followup import API_VERSION, POST_CALL_BUS_CHANNEL


SUPPORTED_API_VERSIONS = {API_VERSION}
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_DURATION_SECONDS = 24 * 60 * 60
ALLOWED_PAYLOAD_FIELDS = {
    "api_version",
    "payload_version",  # deprecated compatibility alias
    "event_id",
    "correlation_id",
    "call_id",
    "source",
    "company_id",
    "agent_user_id",
    "agent_login",
    "lead_id",
    "partner_id",
    "customer_name",
    "customer_email",
    "started_at",
    "ended_at",
    "duration_seconds",
    "call_direction",
    "direction",  # deprecated compatibility alias
    "metadata",
}


class CodestraCrmCallFollowupApi(models.AbstractModel):
    _name = "codestra.crm.call.followup.api"
    _description = "CRM Call Follow-up RPC API"

    @api.model
    def _require_service_user(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_service"
        ):
            raise AccessError(
                _("Only the authenticated call integration service may use this API.")
            )

    @api.model
    def _validate_payload(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError(_("The completed-call payload must be an object."))
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=True,
                default=str,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                _("The completed-call payload is not JSON serializable.")
            ) from exc
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise ValidationError(
                _("PAYLOAD_TOO_LARGE: completed-call payload exceeds 64 KiB.")
            )

        unknown = sorted(set(payload) - ALLOWED_PAYLOAD_FIELDS)
        if unknown:
            raise ValidationError(
                _("UNKNOWN_PAYLOAD_FIELDS: %(fields)s.")
                % {"fields": ", ".join(unknown)}
            )
        metadata = payload.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValidationError(_("metadata must be an object when supplied."))

    @api.model
    def _bounded_text(self, value, label, limit, *, required=False):
        text = str(value or "").strip()
        if required and not text:
            raise ValidationError(_("%s is required.") % label)
        if len(text) > limit:
            raise ValidationError(
                _("%(field)s cannot exceed %(limit)s characters.")
                % {"field": label, "limit": limit}
            )
        return text or False

    @api.model
    def _parse_datetime(self, value, label, *, required=False):
        if not value:
            if required:
                raise ValidationError(_("%s is required.") % label)
            return False
        try:
            return fields.Datetime.to_datetime(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("%s is not a valid date and time.") % label) from exc

    @api.model
    def _normalize_version(self, payload):
        version = self._bounded_text(
            payload.get("api_version")
            or payload.get("payload_version")
            or API_VERSION,
            _("api_version"),
            16,
            required=True,
        )
        if version not in SUPPORTED_API_VERSIONS:
            raise ValidationError(
                _("UNSUPPORTED_API_VERSION: supported versions are %(versions)s.")
                % {"versions": ", ".join(sorted(SUPPORTED_API_VERSIONS))}
            )
        return version

    @api.model
    def _normalize_direction(self, value):
        normalized = str(value or "unknown").strip().lower().replace("-", "_")
        normalized = {
            "in": "inbound",
            "incoming": "inbound",
            "out": "outbound",
            "outgoing": "outbound",
        }.get(normalized, normalized)
        if normalized not in {"inbound", "outbound", "unknown"}:
            raise ValidationError(
                _("call_direction must be inbound, outbound, or unknown.")
            )
        return normalized

    @api.model
    def _resolve_company(self, payload):
        try:
            company_id = int(payload.get("company_id") or self.env.company.id)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("company_id must be an integer.")) from exc
        if company_id not in self.env.user.company_ids.ids:
            raise AccessError(
                _("The integration service is not assigned to this company.")
            )
        company = self.env["res.company"].sudo().browse(company_id).exists()
        if not company:
            raise ValidationError(_("The requested company does not exist."))
        return company

    @api.model
    def _resolve_agent(self, payload, company):
        has_id = bool(payload.get("agent_user_id"))
        has_login = bool(payload.get("agent_login"))
        if has_id == has_login:
            raise ValidationError(
                _("Supply exactly one of agent_user_id or agent_login.")
            )

        Users = self.env["res.users"].sudo().with_context(active_test=True)
        if has_id:
            try:
                agent = Users.browse(int(payload["agent_user_id"])).exists()
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("agent_user_id must be an integer.")) from exc
        else:
            login = self._bounded_text(
                payload["agent_login"], _("agent_login"), 320, required=True
            )
            agent = Users.search([("login", "=", login)], limit=1)

        if not agent or agent.share:
            raise ValidationError(_("A valid active internal agent is required."))
        if company not in agent.company_ids:
            raise AccessError(
                _("The assigned agent does not belong to the event company.")
            )
        if not agent.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            raise AccessError(
                _("The assigned agent is not enabled for the Call Follow-up feature.")
            )
        return agent

    @api.model
    def _resolve_lead(self, payload, company):
        Leads = self.env["crm.lead"].sudo()
        if not payload.get("lead_id"):
            return Leads.browse()
        try:
            lead = Leads.browse(int(payload["lead_id"])).exists()
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("lead_id must be an integer.")) from exc
        if not lead:
            raise ValidationError(_("The requested CRM lead does not exist."))
        if lead.company_id and lead.company_id != company:
            raise AccessError(_("The CRM lead belongs to a different company."))
        return lead

    @api.model
    def _resolve_partner(self, payload, lead, company):
        Partners = self.env["res.partner"].sudo()
        partner = lead.partner_id if lead else Partners.browse()
        if payload.get("partner_id"):
            try:
                partner = Partners.browse(int(payload["partner_id"])).exists()
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("partner_id must be an integer.")) from exc
            if not partner:
                raise ValidationError(_("The requested customer does not exist."))
        if partner.company_id and partner.company_id != company:
            raise AccessError(_("The customer belongs to a different company."))
        if lead and lead.partner_id and partner and lead.partner_id != partner:
            raise ValidationError(
                _("partner_id does not match the customer linked to the CRM lead.")
            )
        return partner

    @api.model
    def _fingerprint(self, material):
        canonical = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    @api.model
    def _material(
        self,
        *,
        version,
        company,
        agent,
        lead,
        partner,
        event_id,
        call_id,
        source,
        direction,
        started_at,
        ended_at,
        duration_seconds,
    ):
        return {
            "payload_version": version,
            "company_id": company.id,
            "agent_id": agent.id,
            "lead_id": lead.id or False,
            "partner_id": partner.id or False,
            "event_id": event_id,
            "call_id": call_id or False,
            "source": source,
            "call_direction": direction,
            "started_at": (
                fields.Datetime.to_string(started_at) if started_at else False
            ),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": duration_seconds,
        }

    @api.model
    def health(self):
        self._require_service_user()
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "model": self._name,
            "server_time": fields.Datetime.to_string(fields.Datetime.now()),
            "public_controller": False,
        }

    @api.model
    def get_contract(self):
        self._require_service_user()
        return {
            "api_version": API_VERSION,
            "model": self._name,
            "compatibility_model": "codestra.crm.call.followup",
            "methods": {
                "health": {"arguments": []},
                "get_contract": {"arguments": []},
                "register_completed_call": {
                    "arguments": ["payload"],
                    "required": [
                        "api_version",
                        "event_id",
                        "company_id",
                        "ended_at",
                        "agent_user_id|agent_login",
                    ],
                    "idempotency_scope": ["company_id", "event_id"],
                },
            },
            "limits": {
                "payload_bytes": MAX_PAYLOAD_BYTES,
                "event_id": 255,
                "source": 64,
                "duration_seconds": MAX_DURATION_SECONDS,
            },
            "security": {
                "authentication": "odoo_api_key",
                "required_group": (
                    "codestra_crm_call_followup.group_call_followup_service"
                ),
                "public_controller": False,
            },
            "schemas": {
                "request": (
                    "odoo_addons/codestra_crm_call_followup/"
                    "contracts/completed_call.v1.schema.json"
                ),
                "response": (
                    "odoo_addons/codestra_crm_call_followup/"
                    "contracts/completed_call.response.v1.schema.json"
                ),
            },
        }

    @api.model
    def register_completed_call(self, payload):
        self._require_service_user()
        self._validate_payload(payload)

        version = self._normalize_version(payload)
        event_id = self._bounded_text(
            payload.get("event_id"), _("event_id"), 255, required=True
        )
        correlation_id = self._bounded_text(
            payload.get("correlation_id"), _("correlation_id"), 255
        )
        call_id = self._bounded_text(payload.get("call_id"), _("call_id"), 255)
        source = self._bounded_text(
            payload.get("source") or "middleware",
            _("source"),
            64,
            required=True,
        )
        direction = self._normalize_direction(
            payload.get("call_direction") or payload.get("direction")
        )

        company = self._resolve_company(payload)
        agent = self._resolve_agent(payload, company)
        lead = self._resolve_lead(payload, company)
        partner = self._resolve_partner(payload, lead, company)
        ended_at = self._parse_datetime(
            payload.get("ended_at"), _("Call end time"), required=True
        )

        try:
            duration_seconds = int(payload.get("duration_seconds") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("duration_seconds must be an integer.")) from exc
        if not 0 <= duration_seconds <= MAX_DURATION_SECONDS:
            raise ValidationError(
                _("duration_seconds must be between 0 and %(maximum)s.")
                % {"maximum": MAX_DURATION_SECONDS}
            )

        started_at = self._parse_datetime(
            payload.get("started_at"), _("Call start time")
        )
        if not started_at and duration_seconds:
            started_at = ended_at - timedelta(seconds=duration_seconds)
        if started_at and started_at > ended_at:
            raise ValidationError(
                _("Call start time cannot be after call end time.")
            )

        material = self._material(
            version=version,
            company=company,
            agent=agent,
            lead=lead,
            partner=partner,
            event_id=event_id,
            call_id=call_id,
            source=source,
            direction=direction,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
        )
        request_fingerprint = self._fingerprint(material)

        Followup = (
            self.env["codestra.crm.call.followup"].sudo().with_company(company)
        )
        domain = [("company_id", "=", company.id), ("event_id", "=", event_id)]
        existing = Followup.search(domain, limit=1)
        if existing:
            return existing._registration_response_for_replay(
                request_fingerprint=request_fingerprint,
                correlation_id=correlation_id,
            )

        customer_name = (
            partner.display_name
            or lead.display_name
            or self._bounded_text(
                payload.get("customer_name"), _("customer_name"), 255
            )
            or _("Customer")
        )
        customer_email = self._bounded_text(
            payload.get("customer_email"), _("customer_email"), 320
        )
        values = {
            "name": _("Post-call follow-up — %s") % customer_name,
            "event_id": event_id,
            "correlation_id": correlation_id,
            "call_id": call_id,
            "source": source,
            "payload_version": version,
            "request_fingerprint": request_fingerprint,
            "call_direction": direction,
            "company_id": company.id,
            "agent_id": agent.id,
            "lead_id": lead.id or False,
            "partner_id": partner.id or False,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "email_to": (
                partner.email
                or lead.email_from
                or customer_email
                or False
            ),
            "email_cc": agent.email or False,
            "popup_requested_at": fields.Datetime.now(),
        }

        try:
            with self.env.cr.savepoint():
                followup = Followup.with_context(
                    codestra_call_ingest=True
                ).create(values)
                created = True
        except IntegrityError:
            followup = Followup.search(domain, limit=1)
            if not followup:
                raise
            return followup._registration_response_for_replay(
                request_fingerprint=request_fingerprint,
                correlation_id=correlation_id,
            )

        if created:
            self.env["bus.bus"].sudo()._sendone(
                agent.partner_id,
                POST_CALL_BUS_CHANNEL,
                {
                    "api_version": API_VERSION,
                    "followup_id": followup.id,
                    "event_id": event_id,
                    "priority": followup.priority,
                    "title": _("Call completed"),
                    "message": _(
                        "Complete the outcome, notes, callback, and customer email."
                    ),
                },
            )
        return followup._registration_response(replayed=False)
