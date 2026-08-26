from __future__ import annotations

import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CodestraCrmCallFollowupHardening(models.Model):
    _inherit = "codestra.crm.call.followup"

    payload_hash = fields.Char(
        string="Registration Fingerprint",
        readonly=True,
        copy=False,
        index=True,
    )
    draft_saved_at = fields.Datetime(readonly=True, copy=False)
    snoozed_until = fields.Datetime(readonly=True, copy=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        fingerprint = self.env.context.get("codestra_registration_payload_hash")
        normalized = []
        for values in vals_list:
            item = dict(values)
            if fingerprint and item.get("event_id"):
                item.setdefault("payload_hash", fingerprint)
            normalized.append(item)
        return super().create(normalized)

    def write(self, values):
        if "payload_hash" in values:
            raise AccessError(_("The completed-call registration fingerprint is immutable."))
        return super().write(values)

    @api.model
    def _resolve_agent(self, payload, company):
        has_user_id = payload.get("agent_user_id") not in (None, False, "")
        has_login = bool(str(payload.get("agent_login") or "").strip())
        if has_user_id == has_login:
            raise ValidationError(
                _("Provide exactly one of agent_user_id or agent_login.")
            )
        return super()._resolve_agent(payload, company)

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
    def _registration_fingerprint(
        self,
        *,
        event_id,
        company,
        agent,
        lead,
        partner,
        started_at,
        ended_at,
        duration_seconds,
        source,
        call_id,
        correlation_id,
    ):
        canonical = {
            "event_id": event_id,
            "company_id": company.id,
            "agent_id": agent.id,
            "lead_id": lead.id or None,
            "partner_id": partner.id or None,
            "started_at": fields.Datetime.to_string(started_at) if started_at else None,
            "ended_at": fields.Datetime.to_string(ended_at),
            "duration_seconds": duration_seconds,
            "source": source,
            "call_id": call_id or None,
            "correlation_id": correlation_id or None,
        }
        encoded = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _stored_registration_fingerprint(self):
        self.ensure_one()
        if self.payload_hash:
            return self.payload_hash
        return self._registration_fingerprint(
            event_id=self.event_id,
            company=self.company_id,
            agent=self.agent_id,
            lead=self.lead_id,
            partner=self.partner_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            duration_seconds=self.duration_seconds or 0,
            source=self.source,
            call_id=self.call_id,
            correlation_id=self.correlation_id,
        )

    def _assert_registration_replay(self, fingerprint):
        self.ensure_one()
        if self._stored_registration_fingerprint() != fingerprint:
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
        fingerprint = self._registration_fingerprint(
            event_id=event_id,
            company=company,
            agent=agent,
            lead=lead,
            partner=partner,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            source=source,
            call_id=call_id,
            correlation_id=correlation_id,
        )

        model = self.sudo().with_company(company)
        domain = [("company_id", "=", company.id), ("event_id", "=", event_id)]
        existing = model.search(domain, limit=1)
        if existing:
            existing._assert_registration_replay(fingerprint)
            return existing._registration_response(replayed=True)

        contextual_self = self.with_context(
            codestra_registration_payload_hash=fingerprint
        )
        result = super(
            CodestraCrmCallFollowupHardening,
            contextual_self,
        ).register_completed_call(payload)
        followup = model.browse(result["followup_id"]).exists()
        if not followup:
            raise ValidationError(_("The completed-call registration was not persisted."))
        followup._assert_registration_replay(fingerprint)
        return result

    @api.model
    def get_pending_post_call_actions(self, limit=5, exclude_ids=None):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            return []
        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 5

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
        return True
