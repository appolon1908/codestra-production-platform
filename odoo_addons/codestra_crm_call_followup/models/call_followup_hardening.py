from __future__ import annotations

import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .call_followup import POST_CALL_BUS_CHANNEL


class CodestraCrmCallFollowupHardening(models.Model):
    _inherit = "codestra.crm.call.followup"

    payload_hash = fields.Char(
        string="Registration Fingerprint",
        readonly=True,
        copy=False,
        index=True,
    )
    payload_hash_version = fields.Integer(readonly=True, copy=False)
    submitted_company_id = fields.Integer(readonly=True, copy=False)
    submitted_agent_user_id = fields.Integer(readonly=True, copy=False)
    submitted_agent_login = fields.Char(readonly=True, copy=False)
    submitted_lead_id = fields.Integer(readonly=True, copy=False)
    submitted_partner_id = fields.Integer(readonly=True, copy=False)
    submitted_customer_name = fields.Char(readonly=True, copy=False)
    submitted_customer_email = fields.Char(readonly=True, copy=False)
    draft_saved_at = fields.Datetime(readonly=True, copy=False)
    snoozed_until = fields.Datetime(readonly=True, copy=False, index=True)

    _registration_identity_fields = {
        "payload_hash",
        "payload_hash_version",
        "submitted_company_id",
        "submitted_agent_user_id",
        "submitted_agent_login",
        "submitted_lead_id",
        "submitted_partner_id",
        "submitted_customer_name",
        "submitted_customer_email",
    }
    _workflow_only_fields = {
        "state",
        "disposition",
        "notes",
        "schedule_kind",
        "callback_at",
        "duration_minutes",
        "calendar_event_id",
        "reminder_email_enabled",
        "send_post_call_email",
        "email_to",
        "email_cc",
        "email_subject",
        "email_body",
        "mail_id",
        "popup_requested_at",
        "popup_completed_at",
        "draft_saved_at",
        "snoozed_until",
        "immediate_delivery_intent_id",
    }

    @api.model_create_multi
    def create(self, vals_list):
        fingerprint = self.env.context.get("codestra_registration_payload_hash")
        metadata = self.env.context.get("codestra_registration_metadata") or {}
        normalized = []
        for values in vals_list:
            item = dict(values)
            if fingerprint and item.get("event_id"):
                item.setdefault("payload_hash", fingerprint)
                item.setdefault("payload_hash_version", 2)
                for field_name in (
                    "submitted_company_id",
                    "submitted_agent_user_id",
                    "submitted_agent_login",
                    "submitted_lead_id",
                    "submitted_partner_id",
                    "submitted_customer_name",
                    "submitted_customer_email",
                ):
                    if metadata.get(field_name) not in (None, False, ""):
                        item.setdefault(field_name, metadata[field_name])
            normalized.append(item)
        return super().create(normalized)

    def write(self, values):
        if self._registration_identity_fields.intersection(values):
            raise AccessError(
                _("The completed-call registration identity is immutable.")
            )
        if self._workflow_only_fields.intersection(values):
            raise AccessError(
                _(
                    "Call outcome, scheduling, delivery, and state fields must be "
                    "changed through an explicit call-follow-up workflow action."
                )
            )
        return super().write(values)

    @api.model
    def _resolve_company(self, payload):
        if payload.get("company_id") in (None, False, ""):
            raise ValidationError(
                _(
                    "company_id is required; the integration session's active "
                    "company is never used as tenant authority."
                )
            )
        return super()._resolve_company(payload)

    @api.model
    def _resolve_agent(self, payload, company):
        has_user_id = payload.get("agent_user_id") not in (None, False, "")
        has_login = bool(str(payload.get("agent_login") or "").strip())
        if has_user_id == has_login:
            raise ValidationError(
                _("Provide exactly one of agent_user_id or agent_login.")
            )
        agent = super()._resolve_agent(payload, company)
        if not agent.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            raise ValidationError(
                _(
                    "The selected user is not assigned the Call Follow-up Agent "
                    "privilege and cannot receive the post-call popup."
                )
            )
        return agent

    @api.model
    def _resolve_partner(self, payload, lead, company):
        partner = super()._resolve_partner(payload, lead, company)
        if lead and lead.partner_id and partner:
            lead_customer = lead.partner_id.commercial_partner_id
            supplied_customer = partner.commercial_partner_id
            if lead_customer != supplied_customer:
                raise ValidationError(
                    _(
                        "partner_id must identify the CRM lead customer or a contact "
                        "belonging to the same commercial entity."
                    )
                )
        return partner

    @api.model
    def _normalize_text(self, value):
        return " ".join(str(value or "").strip().split()) or None

    @api.model
    def _normalize_email(self, value):
        return str(value or "").strip().lower() or None

    @api.model
    def _optional_positive_int(self, value, label):
        if value in (None, False, ""):
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("%s must be an integer.") % label) from exc
        if normalized <= 0:
            raise ValidationError(_("%s must be a positive integer.") % label)
        return normalized

    @api.model
    def _canonical_registration_payload(
        self,
        payload,
        *,
        event_id,
        started_at,
        ended_at,
        duration_seconds,
        source,
        call_id,
        correlation_id,
        fallback_affects_record,
    ):
        return {
            "event_id": event_id,
            "company_id": self._optional_positive_int(
                payload.get("company_id"),
                _("company_id"),
            ),
            "agent_user_id": self._optional_positive_int(
                payload.get("agent_user_id"),
                _("agent_user_id"),
            ),
            "agent_login": self._normalize_text(payload.get("agent_login")),
            "lead_id": self._optional_positive_int(
                payload.get("lead_id"),
                _("lead_id"),
            ),
            "partner_id": self._optional_positive_int(
                payload.get("partner_id"),
                _("partner_id"),
            ),
            # Fallback identity is hashed only when it affects the created
            # business record. CRM-linked customer details are resolved data,
            # not mutable replay identity.
            "customer_name": (
                self._normalize_text(payload.get("customer_name"))
                if fallback_affects_record
                else None
            ),
            "customer_email": (
                self._normalize_email(payload.get("customer_email"))
                if fallback_affects_record
                else None
            ),
            "started_at": (
                fields.Datetime.to_string(started_at) if started_at else None
            ),
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": duration_seconds,
            "source": source,
            "call_id": call_id or None,
            "correlation_id": correlation_id or None,
        }

    @api.model
    def _registration_fingerprint(self, canonical):
        encoded = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @api.model
    def _registration_metadata(self, canonical):
        return {
            "submitted_company_id": canonical["company_id"],
            "submitted_agent_user_id": canonical["agent_user_id"],
            "submitted_agent_login": canonical["agent_login"],
            "submitted_lead_id": canonical["lead_id"],
            "submitted_partner_id": canonical["partner_id"],
            "submitted_customer_name": canonical["customer_name"],
            "submitted_customer_email": canonical["customer_email"],
        }

    def _stored_registration_fingerprint(self):
        self.ensure_one()
        if self.payload_hash:
            return self.payload_hash

        canonical = {
            "event_id": self.event_id,
            "company_id": self.submitted_company_id or self.company_id.id,
            "agent_user_id": self.submitted_agent_user_id or self.agent_id.id,
            "agent_login": self.submitted_agent_login or None,
            "lead_id": self.submitted_lead_id or self.lead_id.id or None,
            "partner_id": self.submitted_partner_id or self.partner_id.id or None,
            "customer_name": self._normalize_text(self.submitted_customer_name),
            "customer_email": self._normalize_email(self.submitted_customer_email),
            "started_at": (
                fields.Datetime.to_string(self.started_at)
                if self.started_at
                else None
            ),
            "ended_at": fields.Datetime.to_string(self.ended_at),
            "duration_seconds": self.duration_seconds or 0,
            "source": self.source,
            "call_id": self.call_id or None,
            "correlation_id": self.correlation_id or None,
        }
        return self._registration_fingerprint(canonical)

    def _legacy_registration_matches(self, canonical):
        self.ensure_one()
        if not canonical:
            return False
        comparisons = (
            (canonical["event_id"], self.event_id),
            (canonical["company_id"], self.company_id.id),
            (canonical["lead_id"], self.lead_id.id or None),
            (
                canonical["started_at"],
                fields.Datetime.to_string(self.started_at)
                if self.started_at
                else None,
            ),
            (canonical["ended_at"], fields.Datetime.to_string(self.ended_at)),
            (canonical["duration_seconds"], self.duration_seconds or 0),
            (canonical["source"], self.source),
            (canonical["call_id"], self.call_id or None),
            (canonical["correlation_id"], self.correlation_id or None),
        )
        if any(left != right for left, right in comparisons):
            return False
        if canonical["agent_user_id"] is not None:
            if canonical["agent_user_id"] != self.agent_id.id:
                return False
        elif canonical["agent_login"] != self._normalize_text(self.agent_id.login):
            return False
        if (
            canonical["partner_id"] is not None
            and canonical["partner_id"] != (self.partner_id.id or None)
        ):
            return False
        if canonical["customer_email"] is not None:
            if canonical["customer_email"] != self._normalize_email(self.email_to):
                return False
        if canonical["customer_name"] is not None:
            stored_name = self.name.rsplit("—", 1)[-1].strip()
            if canonical["customer_name"] != self._normalize_text(stored_name):
                return False
        return True

    def _assert_registration_replay(self, fingerprint, canonical=None):
        self.ensure_one()
        if self.payload_hash_version == 2:
            matches = self._stored_registration_fingerprint() == fingerprint
        else:
            # 19.0.1.1.0 used a resolved-record hash that could change after
            # CRM edits and omitted fallback identity. Compare the immutable
            # stored business fields once, then atomically upgrade the row to
            # the request-derived version-2 identity.
            matches = self._legacy_registration_matches(canonical)
            if matches:
                values = {
                    "payload_hash": fingerprint,
                    "payload_hash_version": 2,
                    **self._registration_metadata(canonical),
                }
                self._write_from_workflow(values)
        if not matches:
            raise ValidationError(
                _(
                    "idempotency_conflict: event_id already exists with different "
                    "immutable completed-call data."
                )
            )

    @api.model
    def register_completed_call(self, payload):
        """Register a completed call and reject conflicting event-id replays."""

        self._require_service_user()
        if not isinstance(payload, dict):
            raise ValidationError(_("The completed-call payload must be an object."))

        event_id = str(payload.get("event_id") or "").strip()
        if not event_id:
            raise ValidationError(_("event_id is required."))
        if len(event_id) > 255:
            raise ValidationError(_("event_id cannot exceed 255 characters."))

        company = self._resolve_company(payload)
        agent = self._resolve_agent(payload, company)
        lead = self._resolve_lead(payload, company)
        partner = self._resolve_partner(payload, lead, company)
        ended_at = self._parse_datetime(
            payload.get("ended_at"),
            _("Call end time"),
            required=True,
        )
        started_at = self._parse_datetime(
            payload.get("started_at"),
            _("Call start time"),
        )
        if started_at and started_at > ended_at:
            raise ValidationError(_("Call start time cannot be after call end time."))

        try:
            duration_seconds = int(payload.get("duration_seconds") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("duration_seconds must be an integer.")) from exc
        if duration_seconds < 0:
            raise ValidationError(_("duration_seconds cannot be negative."))
        if duration_seconds > 86_400:
            raise ValidationError(_("duration_seconds cannot exceed 24 hours."))

        source = str(payload.get("source") or "middleware").strip()
        call_id = str(payload.get("call_id") or "").strip() or False
        correlation_id = str(payload.get("correlation_id") or "").strip() or False
        canonical = self._canonical_registration_payload(
            payload,
            event_id=event_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            source=source,
            call_id=call_id,
            correlation_id=correlation_id,
            fallback_affects_record=not bool(partner),
        )
        fingerprint = self._registration_fingerprint(canonical)

        model = self.sudo().with_company(company)
        domain = [("company_id", "=", company.id), ("event_id", "=", event_id)]
        existing = model.search(domain, limit=1)
        if existing:
            existing._assert_registration_replay(fingerprint, canonical)
            return existing._registration_response(replayed=True)

        contextual_self = self.with_context(
            codestra_registration_payload_hash=fingerprint,
            codestra_registration_metadata=self._registration_metadata(canonical),
        )
        result = super(
            CodestraCrmCallFollowupHardening,
            contextual_self,
        ).register_completed_call(payload)
        followup = model.browse(result["followup_id"]).exists()
        if not followup:
            raise ValidationError(_("The completed-call registration was not persisted."))
        followup._assert_registration_replay(fingerprint, canonical)
        return result

    @api.model
    def get_pending_post_call_actions(
        self,
        limit=5,
        after_ended_at=False,
        after_id=False,
        exclude_ids=None,
    ):
        """Return a stable cursor page ordered by ``ended_at, id``.

        ``exclude_ids`` remains accepted for old clients but is no longer needed
        by the current browser service and never controls pagination progress.
        """

        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            return []
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 5

        if bool(after_ended_at) != bool(after_id):
            raise ValidationError(
                _("after_ended_at and after_id must be supplied together.")
            )

        cursor_time = False
        cursor_id = False
        if after_ended_at:
            cursor_time = self._parse_datetime(
                after_ended_at,
                _("Pending-action cursor time"),
                required=True,
            )
            cursor_id = self._optional_positive_int(
                after_id,
                _("after_id"),
            )

        normalized_exclusions = []
        for value in exclude_ids or []:
            try:
                record_id = int(value)
            except (TypeError, ValueError):
                continue
            if record_id > 0 and record_id not in normalized_exclusions:
                normalized_exclusions.append(record_id)
            if len(normalized_exclusions) >= 200:
                break

        now = fields.Datetime.now()
        domain = [
            ("agent_id", "=", self.env.user.id),
            ("state", "=", "pending"),
            ("popup_completed_at", "=", False),
            "|",
            ("snoozed_until", "=", False),
            ("snoozed_until", "<=", now),
        ]
        if cursor_time:
            domain.extend(
                [
                    "|",
                    ("ended_at", ">", cursor_time),
                    "&",
                    ("ended_at", "=", cursor_time),
                    ("id", ">", cursor_id),
                ]
            )
        if normalized_exclusions:
            domain.append(("id", "not in", normalized_exclusions))

        records = self.search(
            domain,
            order="ended_at asc, id asc",
            limit=limit,
        )
        return [
            {
                "followup_id": record.id,
                "event_id": record.event_id,
                "ended_at": fields.Datetime.to_string(record.ended_at),
                "title": _("Complete post-call follow-up"),
                "message": record.name,
            }
            for record in records
        ]

    def action_cancel_followup(self):
        for record in self:
            current = record.exists()
            if not current:
                continue
            self.env.cr.execute(
                f"SELECT state FROM {current._table} WHERE id = %s FOR UPDATE",
                [current.id],
            )
            row = self.env.cr.fetchone()
            if not row or row[0] != "pending":
                raise ValidationError(_("Only pending call follow-ups can be cancelled."))
            current._write_from_workflow(
                {
                    "state": "cancelled",
                    "popup_completed_at": fields.Datetime.now(),
                    "snoozed_until": False,
                }
            )
            current._cancel_open_reminder_delivery_intents()
            self.env["bus.bus"].sudo()._sendone(
                current.agent_id.partner_id,
                POST_CALL_BUS_CHANNEL,
                {
                    "status": "cancelled",
                    "followup_id": current.id,
                    "event_id": current.event_id,
                },
            )
        return True
