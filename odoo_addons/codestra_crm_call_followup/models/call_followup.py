from __future__ import annotations

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


POST_CALL_BUS_CHANNEL = "codestra_crm_call_followup.post_call"

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


class CodestraCrmCallFollowup(models.Model):
    _name = "codestra.crm.call.followup"
    _description = "CRM Call Follow-up"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "ended_at desc, id desc"

    name = fields.Char(required=True, readonly=True, index=True)
    event_id = fields.Char(required=True, readonly=True, index=True, copy=False)
    correlation_id = fields.Char(readonly=True, index=True, copy=False)
    call_id = fields.Char(readonly=True, index=True, copy=False)
    source = fields.Char(required=True, readonly=True, default="middleware", copy=False)

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
        DISPOSITION_SELECTION,
        tracking=True,
        index=True,
    )
    notes = fields.Html(sanitize=True, tracking=True)

    schedule_kind = fields.Selection(
        SCHEDULE_KIND_SELECTION,
        required=True,
        default="none",
        tracking=True,
    )
    callback_at = fields.Datetime(index=True, tracking=True)
    duration_minutes = fields.Integer(default=30, tracking=True)
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
        "mail.mail",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    email_sent_at = fields.Datetime(readonly=True, copy=False, index=True)

    popup_requested_at = fields.Datetime(readonly=True, copy=False)
    popup_completed_at = fields.Datetime(readonly=True, copy=False)

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

    @api.constrains("schedule_kind", "callback_at")
    def _check_schedule_datetime(self):
        for record in self:
            if record.schedule_kind != "none" and not record.callback_at:
                raise ValidationError(_("A callback or appointment requires a date and time."))

    @api.model
    def _require_service_user(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_service"
        ):
            raise AccessError(
                _("Only the authenticated call integration service may register completed calls.")
            )

    @api.model
    def _parse_datetime(self, value, field_label, required=False):
        if not value:
            if required:
                raise ValidationError(_("%s is required.") % field_label)
            return False
        try:
            return fields.Datetime.to_datetime(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("%s is not a valid date and time.") % field_label) from exc

    @api.model
    def _resolve_company(self, payload):
        company_id = payload.get("company_id") or self.env.company.id
        try:
            company_id = int(company_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("company_id must be an integer.")) from exc

        if company_id not in self.env.user.company_ids.ids:
            raise AccessError(_("The integration service is not assigned to this company."))
        company = self.env["res.company"].sudo().browse(company_id).exists()
        if not company:
            raise ValidationError(_("The requested company does not exist."))
        return company

    @api.model
    def _resolve_agent(self, payload, company):
        users = self.env["res.users"].sudo().with_context(active_test=True)
        agent = users.browse()
        if payload.get("agent_user_id"):
            try:
                agent_id = int(payload["agent_user_id"])
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("agent_user_id must be an integer.")) from exc
            agent = users.browse(agent_id).exists()
        elif payload.get("agent_login"):
            agent = users.search(
                [("login", "=", str(payload["agent_login"]).strip())],
                limit=1,
            )

        if not agent or not agent.active or agent.share:
            raise ValidationError(_("A valid internal agent is required."))
        if company not in agent.company_ids:
            raise AccessError(_("The assigned agent does not belong to the event company."))
        return agent

    @api.model
    def _resolve_lead(self, payload, company):
        leads = self.env["crm.lead"].sudo()
        if not payload.get("lead_id"):
            return leads.browse()
        try:
            lead_id = int(payload["lead_id"])
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("lead_id must be an integer.")) from exc
        lead = leads.browse(lead_id).exists()
        if not lead:
            raise ValidationError(_("The requested CRM lead does not exist."))
        if lead.company_id and lead.company_id != company:
            raise AccessError(_("The CRM lead belongs to a different company."))
        return lead

    @api.model
    def _resolve_partner(self, payload, lead, company):
        partners = self.env["res.partner"].sudo()
        partner = lead.partner_id if lead else partners.browse()
        if payload.get("partner_id"):
            try:
                partner_id = int(payload["partner_id"])
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("partner_id must be an integer.")) from exc
            partner = partners.browse(partner_id).exists()
            if not partner:
                raise ValidationError(_("The requested customer does not exist."))
            if (
                lead
                and lead.partner_id
                and partner.commercial_partner_id
                != lead.partner_id.commercial_partner_id
            ):
                raise ValidationError(
                    _("The requested customer is unrelated to the CRM lead.")
                )
        if partner.company_id and partner.company_id != company:
            raise AccessError(_("The customer belongs to a different company."))
        return partner

    @api.model
    def register_completed_call(self, payload):
        """Create one pending post-call action from an authenticated RPC event.

        The caller must be a dedicated Odoo API-key user in the technical service
        group. ``event_id`` is company-scoped and idempotent. A concurrent duplicate
        returns the first record instead of producing a second popup or calendar item.
        """
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
            payload.get("ended_at") or fields.Datetime.now(),
            _("Call end time"),
            required=True,
        )
        started_at = self._parse_datetime(payload.get("started_at"), _("Call start time"))

        try:
            duration_seconds = int(payload.get("duration_seconds") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("duration_seconds must be an integer.")) from exc
        if duration_seconds < 0:
            raise ValidationError(_("duration_seconds cannot be negative."))

        followup_model = self.sudo().with_company(company)
        domain = [("company_id", "=", company.id), ("event_id", "=", event_id)]
        existing = followup_model.search(domain, limit=1)
        if existing:
            return existing._registration_response(replayed=True)

        customer_name = (
            partner.display_name
            or lead.display_name
            or str(payload.get("customer_name") or _("Customer"))
        )
        email_to = (
            partner.email
            or lead.email_from
            or str(payload.get("customer_email") or "").strip()
            or False
        )
        values = {
            "name": _("Post-call follow-up — %s") % customer_name,
            "event_id": event_id,
            "correlation_id": str(payload.get("correlation_id") or "").strip() or False,
            "call_id": str(payload.get("call_id") or "").strip() or False,
            "source": str(payload.get("source") or "middleware").strip(),
            "company_id": company.id,
            "agent_id": agent.id,
            "lead_id": lead.id or False,
            "partner_id": partner.id or False,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "email_to": email_to,
            "email_cc": agent.email or False,
            "popup_requested_at": fields.Datetime.now(),
        }

        created = False
        try:
            with self.env.cr.savepoint():
                followup = followup_model.create(values)
                created = True
        except IntegrityError:
            followup = followup_model.search(domain, limit=1)
            if not followup:
                raise

        if created:
            self.env["bus.bus"].sudo()._sendone(
                agent.partner_id,
                POST_CALL_BUS_CHANNEL,
                {
                    "followup_id": followup.id,
                    "event_id": event_id,
                    "title": _("Call completed"),
                    "message": _("Complete the outcome, notes, callback, and email."),
                },
            )
        return followup._registration_response(replayed=not created)

    def _registration_response(self, replayed=False):
        self.ensure_one()
        return {
            "followup_id": self.id,
            "event_id": self.event_id,
            "state": self.state,
            "replayed": bool(replayed),
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
        records = self.search(
            [
                ("agent_id", "=", self.env.user.id),
                ("state", "=", "pending"),
                ("popup_completed_at", "=", False),
            ],
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

    def action_open_post_call_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Post-call follow-up"),
            "res_model": "codestra.crm.post.call.wizard",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {"default_followup_id": self.id, "dialog_size": "large"},
        }

    def action_open_calendar_event(self):
        self.ensure_one()
        if not self.calendar_event_id:
            raise ValidationError(_("No callback or appointment has been scheduled."))
        return {
            "type": "ir.actions.act_window",
            "name": self.calendar_event_id.display_name,
            "res_model": "calendar.event",
            "res_id": self.calendar_event_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_cancel_followup(self):
        if any(record.state != "pending" for record in self):
            raise ValidationError(_("Only pending call follow-ups can be cancelled."))
        self._write_from_workflow(
            {
                "state": "cancelled",
                "popup_completed_at": fields.Datetime.now(),
            }
        )
        return True

    def _write_from_workflow(self, values):
        """Apply state changes from trusted server-side workflow methods only."""
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
            "call_id",
            "correlation_id",
        }
        if immutable.intersection(values):
            raise AccessError(_("Completed-call identity fields are immutable."))
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(
                _("Call follow-ups must be changed through the post-call workflow.")
            )
        return super().write(values)
