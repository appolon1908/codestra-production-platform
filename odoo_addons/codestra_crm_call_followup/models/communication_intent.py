from __future__ import annotations

from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


DELIVERY_KINDS = [
    ("post_call_client", "Post-call client email"),
    ("callback_reminder_client", "Callback reminder — client"),
    ("callback_reminder_agent", "Callback reminder — agent"),
]

DELIVERY_STATES = [
    ("pending", "Pending Middleware delivery"),
    ("delivered", "Delivered"),
    ("failed", "Failed"),
    ("suppressed", "Suppressed"),
    ("cancelled", "Cancelled"),
]


class CodestraCrmCallCommunicationIntent(models.Model):
    _name = "codestra.crm.call.communication.intent"
    _description = "CRM Call Communication Intent"
    _order = "due_at asc, id asc"

    name = fields.Char(required=True, readonly=True)
    command_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    followup_id = fields.Many2one(
        "codestra.crm.call.followup",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
        check_company=True,
    )
    kind = fields.Selection(DELIVERY_KINDS, required=True, readonly=True, index=True)
    recipient_role = fields.Selection(
        [("client", "Client"), ("agent", "Agent")],
        required=True,
        readonly=True,
    )
    due_at = fields.Datetime(required=True, readonly=True, index=True)
    email_to = fields.Char(required=True, readonly=True)
    email_cc = fields.Char(readonly=True)
    subject = fields.Char(required=True, readonly=True)
    body_html = fields.Html(required=True, readonly=True, sanitize=True)
    correlation_id = fields.Char(readonly=True, index=True)
    causation_id = fields.Char(readonly=True, index=True)
    state = fields.Selection(
        DELIVERY_STATES,
        required=True,
        readonly=True,
        default="pending",
        index=True,
    )
    provider_reference = fields.Char(readonly=True, copy=False, index=True)
    result_message = fields.Text(readonly=True, copy=False)
    processed_at = fields.Datetime(readonly=True, copy=False)

    _command_unique = models.Constraint(
        "UNIQUE(company_id, command_id)",
        "A communication command can be recorded only once per company.",
    )
    _idempotency_unique = models.Constraint(
        "UNIQUE(company_id, idempotency_key)",
        "A communication idempotency key can be recorded only once per company.",
    )

    @api.model
    def _require_service_user(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_service"
        ):
            raise AccessError(
                _("Only the authenticated Middleware integration service may process communication intents.")
            )

    def _write_from_workflow(self, values):
        return super().write(values)

    def write(self, values):
        raise AccessError(
            _("Communication intents are immutable outside the controlled Middleware result workflow.")
        )

    @api.model
    def get_pending_delivery_intents(self, limit=50):
        """Return due intents to the dedicated Middleware service.

        Middleware remains responsible for consent/suppression, provider delivery,
        idempotent retries, reconciliation, dead-letter handling, and final results.
        """
        self._require_service_user()
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 50
        records = self.sudo().search(
            [
                ("company_id", "in", self.env.user.company_ids.ids),
                ("state", "=", "pending"),
                ("due_at", "<=", fields.Datetime.now()),
            ],
            order="due_at asc, id asc",
            limit=limit,
        )
        return [
            {
                "command_id": record.command_id,
                "idempotency_key": record.idempotency_key,
                "company_id": record.company_id.id,
                "followup_id": record.followup_id.id,
                "event_id": record.followup_id.event_id,
                "kind": record.kind,
                "recipient_role": record.recipient_role,
                "due_at": fields.Datetime.to_string(record.due_at),
                "email_to": record.email_to,
                "email_cc": record.email_cc or False,
                "subject": record.subject,
                "body_html": record.body_html,
                "correlation_id": record.correlation_id or False,
                "causation_id": record.causation_id or False,
            }
            for record in records
        ]

    @api.model
    def record_delivery_result(
        self,
        command_id,
        status,
        provider_reference=False,
        result_message=False,
    ):
        """Record a final Middleware delivery result idempotently."""
        self._require_service_user()
        command_id = str(command_id or "").strip()
        if not command_id:
            raise ValidationError(_("command_id is required."))
        allowed = {"delivered", "failed", "suppressed"}
        if status not in allowed:
            raise ValidationError(
                _("status must be delivered, failed, or suppressed.")
            )
        record = self.sudo().search(
            [
                ("company_id", "in", self.env.user.company_ids.ids),
                ("command_id", "=", command_id),
            ],
            limit=1,
        )
        if not record:
            raise ValidationError(_("The communication command does not exist."))
        self.env.cr.execute(
            f"SELECT state FROM {record._table} WHERE id = %s FOR UPDATE",
            [record.id],
        )
        row = self.env.cr.fetchone()
        current_state = row and row[0]
        if current_state in allowed:
            if current_state != status:
                raise ValidationError(
                    _("delivery_result_conflict: a different final result is already recorded.")
                )
            return {
                "command_id": record.command_id,
                "state": current_state,
                "replayed": True,
            }
        if current_state != "pending":
            raise ValidationError(_("The communication command is not pending."))
        record._write_from_workflow(
            {
                "state": status,
                "provider_reference": str(provider_reference or "").strip() or False,
                "result_message": str(result_message or "").strip() or False,
                "processed_at": fields.Datetime.now(),
            }
        )
        return {
            "command_id": record.command_id,
            "state": status,
            "replayed": False,
        }


class CodestraCrmCallFollowupCommunication(models.Model):
    _inherit = "codestra.crm.call.followup"

    post_call_intent_id = fields.Many2one(
        "codestra.crm.call.communication.intent",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    communication_intent_ids = fields.One2many(
        "codestra.crm.call.communication.intent",
        "followup_id",
        readonly=True,
    )
    reminder_revision = fields.Integer(readonly=True, copy=False, default=0)

    def _communication_body(self, *, recipient_name, reminder=False):
        self.ensure_one()
        if reminder:
            start = fields.Datetime.to_string(self.callback_at) if self.callback_at else ""
            return (
                "<p>Hello %s,</p>"
                "<p>This is a reminder that the callback or appointment begins in 15 minutes.</p>"
                "<p><strong>Starts:</strong> %s</p>"
                "<p>Organizer: %s</p>"
            ) % (recipient_name or _("there"), start, self.agent_id.name)
        return (
            "<p>Hello %s,</p>"
            "<p>Thank you for speaking with %s. We recorded the agreed next step.</p>"
            "<p>Reply to the delivered message if anything needs to be corrected.</p>"
        ) % (recipient_name or _("there"), self.agent_id.name)

    def _create_communication_intent(self, values):
        self.ensure_one()
        model = self.env["codestra.crm.call.communication.intent"].sudo().with_company(
            self.company_id
        )
        command_id = values["command_id"]
        existing = model.search(
            [
                ("company_id", "=", self.company_id.id),
                ("command_id", "=", command_id),
            ],
            limit=1,
        )
        if existing:
            return existing
        try:
            with self.env.cr.savepoint():
                return model.create(values)
        except IntegrityError:
            return model.search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("command_id", "=", command_id),
                ],
                limit=1,
            )

    def _queue_post_call_intent(self, *, email_to, email_cc, subject, body_html):
        self.ensure_one()
        command_id = f"call-followup:{self.company_id.id}:{self.event_id}:post-call-client"
        return self._create_communication_intent(
            {
                "name": _("Post-call client email — %s") % self.display_name,
                "command_id": command_id,
                "idempotency_key": command_id,
                "company_id": self.company_id.id,
                "followup_id": self.id,
                "kind": "post_call_client",
                "recipient_role": "client",
                "due_at": fields.Datetime.now(),
                "email_to": email_to,
                "email_cc": email_cc or False,
                "subject": subject,
                "body_html": body_html,
                "correlation_id": self.correlation_id or False,
                "causation_id": self.event_id,
            }
        )

    def _cancel_pending_reminder_intents(self):
        for followup in self:
            pending = followup.communication_intent_ids.filtered(
                lambda intent: intent.kind.startswith("callback_reminder_")
                and intent.state == "pending"
            )
            if pending:
                pending._write_from_workflow(
                    {
                        "state": "cancelled",
                        "processed_at": fields.Datetime.now(),
                        "result_message": _("Superseded by a schedule change."),
                    }
                )

    def _replace_reminder_intents(self, callback_at=None, enabled=None):
        for followup in self:
            followup._cancel_pending_reminder_intents()
            is_enabled = (
                followup.reminder_email_enabled if enabled is None else bool(enabled)
            )
            callback = callback_at or followup.callback_at
            if not is_enabled or not callback or followup.schedule_kind == "none":
                continue
            revision = followup.reminder_revision + 1
            followup._write_from_workflow({"reminder_revision": revision})
            due_at = max(callback - timedelta(minutes=15), fields.Datetime.now())
            subject = _("Reminder: %s starts in 15 minutes") % followup.name
            recipients = [
                (
                    "client",
                    "callback_reminder_client",
                    followup.partner_id.email
                    or followup.lead_id.email_from
                    or followup.email_to,
                    followup.partner_id.name or followup.lead_id.contact_name,
                ),
                (
                    "agent",
                    "callback_reminder_agent",
                    followup.agent_id.email,
                    followup.agent_id.name,
                ),
            ]
            for role, kind, email_to, recipient_name in recipients:
                if not email_to:
                    raise ValidationError(
                        _("A valid %s email is required for the reminder.") % role
                    )
                command_id = (
                    f"call-followup:{followup.company_id.id}:{followup.event_id}:"
                    f"reminder:{role}:r{revision}"
                )
                followup._create_communication_intent(
                    {
                        "name": _("Callback reminder — %s") % recipient_name,
                        "command_id": command_id,
                        "idempotency_key": command_id,
                        "company_id": followup.company_id.id,
                        "followup_id": followup.id,
                        "kind": kind,
                        "recipient_role": role,
                        "due_at": due_at,
                        "email_to": email_to,
                        "email_cc": False,
                        "subject": subject,
                        "body_html": followup._communication_body(
                            recipient_name=recipient_name,
                            reminder=True,
                        ),
                        "correlation_id": followup.correlation_id or False,
                        "causation_id": followup.event_id,
                    }
                )
        return True
