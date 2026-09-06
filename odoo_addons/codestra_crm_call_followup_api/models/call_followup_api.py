from __future__ import annotations

import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


API_VERSION = "1.0"
MAX_EVENT_ID_LENGTH = 255
MAX_REFERENCE_LENGTH = 255
MAX_SOURCE_LENGTH = 80
MAX_CUSTOMER_NAME_LENGTH = 255

ALLOWED_V1_FIELDS = frozenset(
    {
        "api_version",
        "event_id",
        "correlation_id",
        "call_id",
        "source",
        "producer",
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
    }
)

FINGERPRINT_FIELDS = (
    "event_id",
    "call_id",
    "source",
    "producer",
    "company_id",
    "agent_user_id",
    "lead_id",
    "partner_id",
    "customer_name",
    "customer_email",
    "started_at",
    "ended_at",
    "duration_seconds",
)


class CodestraCrmCallFollowupApi(models.Model):
    _inherit = "codestra.crm.call.followup"

    api_version = fields.Char(
        readonly=True,
        copy=False,
        index=True,
        default=API_VERSION,
    )
    producer = fields.Char(readonly=True, copy=False, index=True)
    request_fingerprint = fields.Char(readonly=True, copy=False, index=True)
    request_received_at = fields.Datetime(readonly=True, copy=False)

    @api.model
    def _api_require_service_user(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_service"
        ):
            raise AccessError(
                _("Only the authenticated call integration service may use this API.")
            )

    @api.model
    def _api_clean_string(self, payload, key, maximum, required=False):
        value = str(payload.get(key) or "").strip()
        if required and not value:
            raise ValidationError(_("%s is required.") % key)
        if len(value) > maximum:
            raise ValidationError(
                _("%(field)s cannot exceed %(maximum)s characters.")
                % {"field": key, "maximum": maximum}
            )
        return value or False

    @api.model
    def _api_normalize_payload(self, payload, strict=False):
        self._api_require_service_user()
        if not isinstance(payload, dict):
            raise ValidationError(_("The completed-call payload must be an object."))

        unknown = sorted(set(payload) - ALLOWED_V1_FIELDS)
        if strict and unknown:
            raise ValidationError(
                _("Unsupported completed-call fields: %s") % ", ".join(unknown)
            )

        normalized = {
            key: payload[key]
            for key in ALLOWED_V1_FIELDS
            if key in payload
        }
        normalized["api_version"] = API_VERSION

        event_id = self._api_clean_string(
            normalized,
            "event_id",
            MAX_EVENT_ID_LENGTH,
            required=True,
        )
        normalized["event_id"] = event_id

        normalized["call_id"] = self._api_clean_string(
            normalized,
            "call_id",
            MAX_REFERENCE_LENGTH,
        )
        normalized["correlation_id"] = self._api_clean_string(
            normalized,
            "correlation_id",
            MAX_REFERENCE_LENGTH,
        )
        normalized["source"] = self._api_clean_string(
            normalized,
            "source",
            MAX_SOURCE_LENGTH,
        ) or "middleware"
        normalized["producer"] = self._api_clean_string(
            normalized,
            "producer",
            MAX_SOURCE_LENGTH,
        ) or normalized["source"]
        normalized["customer_name"] = self._api_clean_string(
            normalized,
            "customer_name",
            MAX_CUSTOMER_NAME_LENGTH,
        )

        if strict and not normalized.get("company_id"):
            raise ValidationError(_("company_id is required by the v1 API."))
        if strict and not normalized.get("ended_at"):
            raise ValidationError(_("ended_at is required by the v1 API."))
        if not normalized.get("agent_user_id") and not normalized.get("agent_login"):
            raise ValidationError(
                _("agent_user_id or agent_login is required.")
            )

        company = self._resolve_company(normalized)
        normalized["company_id"] = company.id

        agent = self._resolve_agent(normalized, company)
        if normalized.get("agent_login"):
            supplied_login = str(normalized["agent_login"]).strip()
            if supplied_login and supplied_login != agent.login:
                raise ValidationError(
                    _("agent_user_id and agent_login identify different users.")
                )
        normalized["agent_user_id"] = agent.id
        normalized.pop("agent_login", None)

        lead = self._resolve_lead(normalized, company)
        partner = self._resolve_partner(normalized, lead, company)
        if lead and lead.partner_id and partner and lead.partner_id != partner:
            raise ValidationError(
                _("partner_id does not match the customer linked to lead_id.")
            )
        normalized["lead_id"] = lead.id or False
        normalized["partner_id"] = partner.id or False

        ended_at = self._parse_datetime(
            normalized.get("ended_at") or fields.Datetime.now(),
            _("Call end time"),
            required=True,
        )
        started_at = self._parse_datetime(
            normalized.get("started_at"),
            _("Call start time"),
        )
        if started_at and started_at > ended_at:
            raise ValidationError(
                _("started_at cannot be later than ended_at.")
            )
        normalized["started_at"] = (
            fields.Datetime.to_string(started_at) if started_at else False
        )
        normalized["ended_at"] = fields.Datetime.to_string(ended_at)

        try:
            duration_seconds = int(normalized.get("duration_seconds") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                _("duration_seconds must be an integer.")
            ) from exc
        if duration_seconds < 0:
            raise ValidationError(_("duration_seconds cannot be negative."))
        normalized["duration_seconds"] = duration_seconds

        if normalized.get("customer_email"):
            normalized["customer_email"] = str(
                normalized["customer_email"]
            ).strip().lower() or False

        return normalized

    @api.model
    def _api_fingerprint(self, payload):
        canonical = {
            key: payload.get(key) or False
            for key in FINGERPRINT_FIELDS
        }
        raw = json.dumps(
            canonical,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _api_assert_or_record_fingerprint(self, fingerprint, producer):
        self.ensure_one()
        if self.request_fingerprint and self.request_fingerprint != fingerprint:
            raise ValidationError(
                _(
                    "event_id was already accepted with a different immutable "
                    "payload. Reuse the original payload or issue a new event_id."
                )
            )
        values = {}
        if not self.request_fingerprint:
            values["request_fingerprint"] = fingerprint
        if not self.request_received_at:
            values["request_received_at"] = fields.Datetime.now()
        if not self.producer:
            values["producer"] = producer
        if not self.api_version:
            values["api_version"] = API_VERSION
        if values:
            self._write_from_workflow(values)

    @api.model
    def register_completed_call(self, payload):
        strict = bool(self.env.context.get("codestra_call_api_strict"))
        normalized = self._api_normalize_payload(payload, strict=strict)
        fingerprint = self._api_fingerprint(normalized)
        company = self.env["res.company"].browse(normalized["company_id"])
        event_id = normalized["event_id"]

        existing = self.sudo().with_company(company).search(
            [
                ("company_id", "=", company.id),
                ("event_id", "=", event_id),
            ],
            limit=1,
        )
        if existing:
            existing._api_assert_or_record_fingerprint(
                fingerprint,
                normalized["producer"],
            )
            return existing._registration_response(replayed=True)

        response = super().register_completed_call(normalized)
        followup = self.sudo().browse(response["followup_id"]).exists()
        if not followup:
            raise ValidationError(
                _("The completed-call event was accepted but cannot be reconciled.")
            )
        followup._api_assert_or_record_fingerprint(
            fingerprint,
            normalized["producer"],
        )
        return followup._registration_response(
            replayed=bool(response.get("replayed"))
        )

    @api.model
    def register_completed_call_v1(self, payload):
        """Strict, versioned entry point for middleware and provider adapters."""
        return self.with_context(
            codestra_call_api_strict=True
        ).register_completed_call(payload)

    @api.model
    def validate_completed_call_v1(self, payload):
        """Validate and fingerprint a payload without creating a CRM record."""
        normalized = self._api_normalize_payload(payload, strict=True)
        return {
            "api_version": API_VERSION,
            "valid": True,
            "event_id": normalized["event_id"],
            "company_id": normalized["company_id"],
            "agent_user_id": normalized["agent_user_id"],
            "request_fingerprint": self._api_fingerprint(normalized),
        }

    @api.model
    def get_integration_capabilities(self):
        self._api_require_service_user()
        return {
            "api_version": API_VERSION,
            "model": "codestra.crm.call.followup",
            "methods": {
                "register": "register_completed_call_v1",
                "validate": "validate_completed_call_v1",
                "status": "get_completed_call_status_v1",
            },
            "idempotency": {
                "scope": "company_id,event_id",
                "conflicting_replay": "rejected",
            },
            "limits": {
                "max_event_id_length": MAX_EVENT_ID_LENGTH,
                "max_batch_size": 1,
            },
            "required_fields": [
                "event_id",
                "company_id",
                "ended_at",
                "agent_user_id|agent_login",
            ],
            "allowed_fields": sorted(ALLOWED_V1_FIELDS),
        }

    @api.model
    def get_completed_call_status_v1(self, company_id, event_id):
        self._api_require_service_user()
        company = self._resolve_company({"company_id": company_id})
        event_id = str(event_id or "").strip()
        if not event_id:
            raise ValidationError(_("event_id is required."))
        followup = self.sudo().with_company(company).search(
            [
                ("company_id", "=", company.id),
                ("event_id", "=", event_id),
            ],
            limit=1,
        )
        if not followup:
            return {
                "api_version": API_VERSION,
                "found": False,
                "event_id": event_id,
                "company_id": company.id,
            }
        response = followup._registration_response(replayed=True)
        response.update(
            {
                "found": True,
                "company_id": company.id,
                "disposition": followup.disposition or False,
                "schedule_kind": followup.schedule_kind,
                "callback_at": followup.callback_at
                and fields.Datetime.to_string(followup.callback_at)
                or False,
            }
        )
        return response

    def _registration_response(self, replayed=False):
        response = super()._registration_response(replayed=replayed)
        self.ensure_one()
        response.update(
            {
                "api_version": self.api_version or API_VERSION,
                "accepted": True,
                "company_id": self.company_id.id,
                "correlation_id": self.correlation_id or False,
                "call_id": self.call_id or False,
                "request_fingerprint": self.request_fingerprint or False,
            }
        )
        return response
