from __future__ import annotations

import hmac
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


API_VERSION = "1.0"
POST_CALL_BUS_CHANNEL = "codestra_crm_call_followup.post_call"
MAX_SNOOZE_MINUTES = 24 * 60

DISPOSITION_SELECTION = [
    ("contacted", "Contacted"),
    ("callback", "Callback Requested"),
    ("appointment", "Appointment Booked"),
    ("sale", "Sale / Conversion"),
    ("no_answer", "No Answer"),
    ("voicemail", "Voicemail"),
    ("wrong_number", "Wrong Number"),
    ("do_not_call", "Do Not Call"),
    ("not_interested", "Not Interested"),
    ("other", "Other"),
]
SCHEDULE_KIND_SELECTION = [
    ("none", "No Schedule"),
    ("callback", "Callback"),
    ("appointment", "Appointment"),
]
PRIORITY_SELECTION = [
    ("normal", "Normal"),
    ("high", "High"),
    ("urgent", "Urgent"),
]
SENTIMENT_SELECTION = [
    ("positive", "Positive"),
    ("neutral", "Neutral"),
    ("negative", "Negative"),
]
CONTACT_CHANNEL_SELECTION = [
    ("phone", "Phone"),
    ("video", "Video"),
    ("in_person", "In Person"),
]
COMPLIANCE_REVIEW_DISPOSITIONS = {"do_not_call", "wrong_number"}


class CodestraCrmCallFollowup(models.Model):
    _name = "codestra.crm.call.followup"
    _description = "CRM Call Follow-up"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "ended_at desc, id desc"

    name = fields.Char(required=True, readonly=True, index=True)
    event_id = fields.Char(required=True, readonly=True, index=True, copy=False)
    correlation_id = fields.Char(readonly=True, index=True, copy=False)
    call_id = fields.Char(readonly=True, index=True, copy=False)
    source = fields.Char(
        required=True, readonly=True, default="middleware", copy=False
    )
    payload_version = fields.Char(
        required=True,
        readonly=True,
        default=API_VERSION,
        index=True,
        copy=False,
    )
    request_fingerprint = fields.Char(readonly=True, index=True, copy=False)
    call_direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound"), ("unknown", "Unknown")],
        required=True,
        default="unknown",
        readonly=True,
        index=True,
        copy=False,
    )

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        readonly=True,
    )
    agent_id = fields.Many2one(
        "res.users",
        required=True,
        index=True,
        readonly=True,
        tracking=True,
        ondelete="restrict",
    )
    lead_id = fields.Many2one(
        "crm.lead",
        index=True,
        readonly=True,
        tracking=True,
        ondelete="set null",
        check_company=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        index=True,
        readonly=True,
        tracking=True,
        ondelete="set null",
        check_company=True,
    )

    started_at = fields.Datetime(readonly=True, index=True)
    ended_at = fields.Datetime(required=True, readonly=True, index=True)
    duration_seconds = fields.Integer(readonly=True)

    state = fields.Selection(
        [
            ("pending", "Needs Follow-up"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending",
        index=True,
        tracking=True,
    )
    disposition = fields.Selection(
        DISPOSITION_SELECTION, tracking=True, index=True
    )
    notes = fields.Html(sanitize=True, tracking=True)
    priority = fields.Selection(
        PRIORITY_SELECTION,
        required=True,
        default="normal",
        tracking=True,
        index=True,
    )
    priority_rank = fields.Integer(
        compute="_compute_priority_rank", store=True, index=True
    )
    customer_sentiment = fields.Selection(
        SENTIMENT_SELECTION, tracking=True, index=True
    )
    compliance_review_required = fields.Boolean(
        readonly=True, tracking=True, index=True, copy=False
    )

    schedule_kind = fields.Selection(
        SCHEDULE_KIND_SELECTION,
        required=True,
        default="none",
        tracking=True,
    )
    callback_at = fields.Datetime(index=True, tracking=True)
    duration_minutes = fields.Integer(default=30, tracking=True)
    contact_channel = fields.Selection(
        CONTACT_CHANNEL_SELECTION,
        required=True,
        default="phone",
        tracking=True,
    )
    meeting_location = fields.Char(tracking=True)
    calendar_event_id = fields.Many2one(
        "calendar.event",
        readonly=True,
        tracking=True,
        ondelete="set null",
        copy=False,
    )
    reminder_email_enabled = fields.Boolean(default=True, tracking=True)

    send_post_call_email = fields.Boolean(default=True)
    email_to = fields.Char()
    email_cc = fields.Char()
    email_subject = fields.Char()
    email_body = fields.Html(sanitize=True)
    mail_id = fields.Many2one(
        "mail.mail", readonly=True, copy=False, ondelete="set null"
    )

    popup_requested_at = fields.Datetime(readonly=True, copy=False)
    popup_completed_at = fields.Datetime(readonly=True, copy=False)
    snoozed_until = fields.Datetime(readonly=True, index=True, copy=False)
    completed_at = fields.Datetime(readonly=True, index=True, copy=False)
    completed_by_id = fields.Many2one(
        "res.users", readonly=True, ondelete="set null", copy=False
    )

    _event_unique = models.Constraint(
        "UNIQUE(company_id, event_id)",
        "A completed-call event can be registered only once per company.",
    )
    _duration_non_negative = models.Constraint(
        "CHECK(duration_seconds IS NULL OR duration_seconds >= 0)",
        "Call duration cannot be negative.",
    )
    _appointment_duration_positive = models.Constraint(
        "CHECK(duration_minutes > 0)",
        "Callback or appointment duration must be greater than zero.",
    )

    @api.depends("priority")
    def _compute_priority_rank(self):
        ranks = {"normal": 0, "high": 1, "urgent": 2}
        for record in self:
            record.priority_rank = ranks.get(record.priority, 0)

    @api.constrains("schedule_kind", "callback_at")
    def _check_schedule_datetime(self):
        for record in self:
            if record.schedule_kind != "none" and not record.callback_at:
                raise ValidationError(
                    _("A callback or appointment requires a date and time.")
                )

    @api.ondelete(at_uninstall=False)
    def _prevent_audit_deletion(self):
        raise AccessError(
            _("Completed-call follow-up records are an immutable audit trail.")
        )

    @api.model
    def register_completed_call(self, payload):
        """Compatibility RPC delegate for the versioned API model."""
        return self.env[
            "codestra.crm.call.followup.api"
        ].register_completed_call(payload)

    @api.model
    def get_api_contract(self):
        return self.env["codestra.crm.call.followup.api"].get_contract()

    @api.model
    def get_api_health(self):
        return self.env["codestra.crm.call.followup.api"].health()

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.context.get("codestra_call_ingest"):
            raise AccessError(
                _(
                    "Completed-call records may be created only by "
                    "the ingestion workflow."
                )
            )
        return super().create(values_list)

    def _registration_response_for_replay(
        self, request_fingerprint, correlation_id=False
    ):
        self.ensure_one()
        if self.request_fingerprint and not hmac.compare_digest(
            self.request_fingerprint, request_fingerprint
        ):
            raise ValidationError(
                _(
                    "IDEMPOTENCY_CONFLICT: event_id %(event)s was already "
                    "accepted with different immutable call data."
                )
                % {"event": self.event_id}
            )
        updates = {}
        if not self.request_fingerprint:
            updates["request_fingerprint"] = request_fingerprint
        if correlation_id and not self.correlation_id:
            updates["correlation_id"] = correlation_id
        if updates:
            self._write_from_workflow(updates)
        return self._registration_response(replayed=True)

    def _registration_response(self, replayed=False):
        self.ensure_one()
        return {
            "api_version": API_VERSION,
            "status": "accepted",
            "created": not bool(replayed),
            "replayed": bool(replayed),
            "followup_id": self.id,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id or False,
            "state": self.state,
            "next_action": (
                "post_call_popup" if self.state == "pending" else "none"
            ),
        }

    @api.model
    def get_pending_post_call_actions(self, limit=5):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            return []
        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 5

        now = fields.Datetime.now()
        records = self.search(
            [
                ("agent_id", "=", self.env.user.id),
                ("state", "=", "pending"),
                ("popup_completed_at", "=", False),
                "|",
                ("snoozed_until", "=", False),
                ("snoozed_until", "<=", now),
            ],
            order="priority_rank desc, ended_at asc, id asc",
            limit=limit,
        )
        return [
            {
                "api_version": API_VERSION,
                "followup_id": record.id,
                "event_id": record.event_id,
                "title": _("Complete post-call follow-up"),
                "message": record.name,
                "priority": record.priority,
                "ended_at": fields.Datetime.to_string(record.ended_at),
            }
            for record in records
        ]

    def _lock_for_completion(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM codestra_crm_call_followup "
            "WHERE id = %s FOR UPDATE",
            [self.id],
        )
        locked = self.browse(self.id)
        locked.invalidate_recordset()
        return locked

    def action_open_post_call_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Post-call follow-up"),
            "res_model": "codestra.crm.post.call.wizard",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_followup_id": self.id,
                "dialog_size": "large",
            },
        }

    def action_open_calendar_event(self):
        self.ensure_one()
        if not self.calendar_event_id:
            raise ValidationError(
                _("No callback or appointment has been scheduled.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.calendar_event_id.display_name,
            "res_model": "calendar.event",
            "res_id": self.calendar_event_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_open_related_record(self):
        self.ensure_one()
        if self.lead_id:
            model, record = "crm.lead", self.lead_id
        elif self.partner_id:
            model, record = "res.partner", self.partner_id
        else:
            raise ValidationError(
                _("No CRM lead or customer is linked to this call.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": record.display_name,
            "res_model": model,
            "res_id": record.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_snooze(self, minutes=10):
        try:
            minutes = int(minutes)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                _("Snooze duration must be an integer.")
            ) from exc
        if not 5 <= minutes <= MAX_SNOOZE_MINUTES:
            raise ValidationError(
                _("Snooze duration must be between 5 minutes and 24 hours.")
            )

        for record in self:
            locked = record._lock_for_completion()
            if locked.state != "pending":
                raise ValidationError(
                    _("Only pending call follow-ups can be snoozed.")
                )
            locked._write_from_workflow(
                {
                    "snoozed_until": (
                        fields.Datetime.now()
                        + timedelta(minutes=minutes)
                    )
                }
            )
        return True

    def action_snooze_10_minutes(self):
        return self.action_snooze(minutes=10)

    def action_cancel_followup(self):
        for record in self:
            locked = record._lock_for_completion()
            if locked.state != "pending":
                raise ValidationError(
                    _("Only pending call follow-ups can be cancelled.")
                )
            locked._write_from_workflow(
                {
                    "state": "cancelled",
                    "snoozed_until": False,
                    "popup_completed_at": fields.Datetime.now(),
                }
            )
        return True

    def _write_from_workflow(self, values):
        """Apply state changes from trusted server-side workflow methods."""
        return super().write(values)

    def write(self, values):
        immutable = {
            "event_id",
            "company_id",
            "agent_id",
            "lead_id",
            "partner_id",
            "started_at",
            "ended_at",
            "duration_seconds",
            "source",
            "payload_version",
            "request_fingerprint",
            "call_direction",
            "call_id",
            "correlation_id",
        }
        if immutable.intersection(values):
            raise AccessError(
                _("Completed-call identity fields are immutable.")
            )
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(
                _(
                    "Call follow-ups must be changed through "
                    "the post-call workflow."
                )
            )
        return super().write(values)
