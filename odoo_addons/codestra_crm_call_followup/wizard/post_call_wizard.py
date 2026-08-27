from __future__ import annotations

from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tools import email_split

from ..models.call_followup import (
    DISPOSITION_SELECTION,
    POST_CALL_BUS_CHANNEL,
    SCHEDULE_KIND_SELECTION,
)


class CodestraCrmPostCallWizard(models.TransientModel):
    _name = "codestra.crm.post.call.wizard"
    _description = "Complete CRM Post-call Follow-up"

    followup_id = fields.Many2one(
        "codestra.crm.call.followup",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    lead_id = fields.Many2one(related="followup_id.lead_id", readonly=True)
    partner_id = fields.Many2one(related="followup_id.partner_id", readonly=True)
    agent_id = fields.Many2one(related="followup_id.agent_id", readonly=True)
    call_ended_at = fields.Datetime(related="followup_id.ended_at", readonly=True)
    call_duration_seconds = fields.Integer(
        related="followup_id.duration_seconds",
        readonly=True,
    )

    disposition = fields.Selection(DISPOSITION_SELECTION, required=True)
    notes = fields.Html(sanitize=True)

    schedule_kind = fields.Selection(
        SCHEDULE_KIND_SELECTION,
        required=True,
        default="none",
    )
    callback_at = fields.Datetime(string="Date and Time")
    duration_minutes = fields.Integer(default=30)
    reminder_email_enabled = fields.Boolean(
        string="Email client and agent 15 minutes before",
        default=True,
        help=(
            "Creates durable email intents for Codestra Middleware. Odoo does not "
            "send the reminder directly."
        ),
    )

    send_post_call_email = fields.Boolean(
        string="Send follow-up email now",
        default=True,
        help=(
            "Creates a durable email intent for Codestra Middleware. Odoo does not "
            "send the message directly."
        ),
    )
    email_to = fields.Char(string="To")
    email_cc = fields.Char(string="CC")
    email_subject = fields.Char(string="Subject")
    email_body = fields.Html(string="Email", sanitize=True)
    delivery_intent_id = fields.Many2one(
        "codestra.crm.call.delivery.intent",
        readonly=True,
    )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        followup_id = values.get("followup_id") or self.env.context.get(
            "default_followup_id"
        )
        followup = self.env["codestra.crm.call.followup"].browse(
            followup_id
        ).exists()
        if not followup:
            return values

        values.update(
            {
                "disposition": followup.disposition or "contacted",
                "notes": followup.notes,
                "schedule_kind": followup.schedule_kind or "none",
                "callback_at": followup.callback_at,
                "duration_minutes": followup.duration_minutes or 30,
                "reminder_email_enabled": followup.reminder_email_enabled,
                "send_post_call_email": followup.send_post_call_email,
                "email_to": followup.email_to,
                "email_cc": followup.email_cc or followup.agent_id.email,
                "email_subject": followup.email_subject,
                "email_body": followup.email_body,
            }
        )
        if not values.get("email_subject") or not values.get("email_body"):
            generated = self._render_default_email(followup)
            if not values.get("email_subject"):
                values["email_subject"] = generated.get("subject")
            if not values.get("email_body"):
                values["email_body"] = generated.get("body_html")
        return values

    @api.model
    def _render_default_email(self, followup):
        template = self.env.ref(
            "codestra_crm_call_followup.mail_template_post_call_followup",
            raise_if_not_found=False,
        )
        if not template:
            return {}
        rendered = template.sudo()._generate_template(
            [followup.id],
            ["subject", "body_html"],
        )
        return rendered.get(followup.id, {})

    @api.onchange("schedule_kind")
    def _onchange_schedule_kind(self):
        if self.schedule_kind == "none":
            self.callback_at = False
            return
        if not self.callback_at:
            self.callback_at = fields.Datetime.now() + timedelta(hours=1)
        if self.schedule_kind == "callback":
            self.disposition = "callback"
        elif self.schedule_kind == "appointment":
            self.disposition = "appointment"

    @api.onchange("send_post_call_email")
    def _onchange_send_post_call_email(self):
        if self.send_post_call_email and not self.email_to:
            self.email_to = (
                self.followup_id.partner_id.email
                or self.followup_id.lead_id.email_from
                or False
            )

    def _validate_email_list(self, value, label, required=False):
        value = (value or "").strip()
        if not value:
            if required:
                raise ValidationError(_("%s is required.") % label)
            return
        if not email_split(value):
            raise ValidationError(
                _("%s does not contain a valid email address.") % label
            )

    def _validate_completion(self):
        self.ensure_one()
        if not self.disposition:
            raise ValidationError(_("Select a call outcome."))
        if (
            self.disposition in {"do_not_call", "wrong_number"}
            and self.schedule_kind != "none"
        ):
            raise ValidationError(
                _("A do-not-call or wrong-number outcome cannot have an appointment.")
            )

        if self.send_post_call_email:
            self._validate_email_list(
                self.email_to,
                _("Recipient"),
                required=True,
            )
            self._validate_email_list(self.email_cc, _("CC"), required=False)
            if not (self.email_subject or "").strip():
                raise ValidationError(_("The email subject is required."))
            if not self.email_body:
                raise ValidationError(_("The email body is required."))

        if self.schedule_kind == "none":
            return
        if not self.callback_at:
            raise ValidationError(_("Choose a callback or appointment date and time."))
        if self.callback_at <= fields.Datetime.now():
            raise ValidationError(_("The callback or appointment must be in the future."))
        if not 5 <= self.duration_minutes <= 480:
            raise ValidationError(
                _("The duration must be between 5 and 480 minutes.")
            )

        if self.reminder_email_enabled:
            if not self.followup_id.partner_id:
                raise ValidationError(
                    _(
                        "Link the CRM lead to a customer/contact before enabling "
                        "client reminders."
                    )
                )
            self._validate_email_list(
                self.followup_id.partner_id.email,
                _("Client email"),
                required=True,
            )
            self._validate_email_list(
                self.followup_id.agent_id.email,
                _("Agent email"),
                required=True,
            )

    def _calendar_alarm_ids(self):
        # Odoo owns only the internal 30-minute preparation notification.
        # Middleware owns every external reminder email.
        return [
            self.env.ref(
                "codestra_crm_call_followup.calendar_alarm_prepare_30_minutes"
            ).id
        ]

    def _calendar_event_values(self):
        followup = self.followup_id
        client = followup.partner_id or followup.lead_id.partner_id
        client_name = (
            client.display_name
            or followup.lead_id.display_name
            or _("Customer")
        )
        title = (
            _("Callback with %s") % client_name
            if self.schedule_kind == "callback"
            else _("Appointment with %s") % client_name
        )
        stop = self.callback_at + timedelta(minutes=self.duration_minutes)
        description = Markup("<p><strong>%s</strong></p>") % _(
            "Prepared from the completed-call CRM workflow."
        )
        if self.notes:
            description += Markup(self.notes)
        else:
            description += Markup("<p>%s</p>") % _("No additional notes.")
        return {
            "name": title,
            "start": self.callback_at,
            "stop": stop,
            "user_id": followup.agent_id.id,
            # Client attendees are deliberately excluded. Native Odoo calendar
            # invitations and updates are not an authorized delivery channel.
            "partner_ids": [Command.set([followup.agent_id.partner_id.id])],
            "alarm_ids": [Command.set(self._calendar_alarm_ids())],
            "description": description,
            "codestra_call_followup_id": followup.id,
            "codestra_schedule_kind": self.schedule_kind,
            "active": True,
        }

    def _schedule_or_remove_calendar_event(self):
        followup = self.followup_id
        event = followup.calendar_event_id
        context = {
            "skip_codestra_followup_sync": True,
            "no_mail_to_attendees": True,
            "mail_notify_force_send": False,
        }
        if self.schedule_kind == "none":
            if event:
                event.with_context(**context).unlink()
            return self.env["calendar.event"].browse()

        values = self._calendar_event_values()
        if event:
            event.with_context(**context).write(values)
            return event
        return self.env["calendar.event"].with_context(**context).create(values)

    def _queue_post_call_email(self):
        """Record a local intent; Middleware performs the external delivery."""

        if not self.send_post_call_email:
            self.delivery_intent_id = False
            return self.env["codestra.crm.call.delivery.intent"].browse()

        followup = self.followup_id
        intent = followup._create_delivery_intent(
            intent_type="post_call_email",
            audience="client",
            idempotency_key=(
                f"call-followup:{followup.company_id.id}:{followup.id}:"
                "post-call-email:v1"
            ),
            available_at=fields.Datetime.now(),
            recipient_to=self.email_to.strip(),
            recipient_cc=(self.email_cc or "").strip() or False,
            subject=self.email_subject.strip(),
            body_html=self.email_body,
        )
        self.delivery_intent_id = intent
        return intent

    def _post_chatter_summary(self, event):
        followup = self.followup_id
        if not followup.lead_id:
            return
        disposition_label = dict(DISPOSITION_SELECTION).get(
            self.disposition,
            self.disposition,
        )
        schedule_text = _("No callback scheduled")
        if event:
            schedule_text = _("%s scheduled for %s") % (
                dict(SCHEDULE_KIND_SELECTION).get(
                    self.schedule_kind,
                    self.schedule_kind,
                ),
                fields.Datetime.to_string(self.callback_at),
            )
        body = Markup(
            "<p><strong>%s</strong></p>"
            "<p>%s: %s<br/>%s</p>"
        ) % (
            _("Post-call follow-up completed"),
            _("Outcome"),
            disposition_label,
            schedule_text,
        )
        if self.notes:
            body += Markup("<p><strong>%s</strong></p>") % _("Agent notes")
            body += Markup(self.notes)
        followup.lead_id.message_post(
            body=body,
            subtype_xmlid="mail.mt_note",
        )

    def _claim_pending_followup(self):
        """Serialize completion and reject stale/replayed wizard submissions."""

        self.ensure_one()
        followup = self.followup_id.exists()
        if not followup:
            return False
        self.env.cr.execute(
            f"SELECT id FROM {followup._table} "
            "WHERE id = %s AND state = 'pending' FOR UPDATE",
            [followup.id],
        )
        return bool(self.env.cr.fetchone())

    def action_complete(self):
        self.ensure_one()
        self._validate_completion()
        if not self._claim_pending_followup():
            return {"type": "ir.actions.act_window_close"}

        event = self._schedule_or_remove_calendar_event()
        intent = self._queue_post_call_email()
        values = {
            "state": "completed",
            "disposition": self.disposition,
            "notes": self.notes,
            "schedule_kind": self.schedule_kind,
            "callback_at": (
                self.callback_at if self.schedule_kind != "none" else False
            ),
            "duration_minutes": self.duration_minutes,
            "calendar_event_id": event.id or False,
            "reminder_email_enabled": self.reminder_email_enabled,
            "send_post_call_email": self.send_post_call_email,
            "email_to": self.email_to,
            "email_cc": self.email_cc,
            "email_subject": self.email_subject,
            "email_body": self.email_body,
            "mail_id": False,
            "immediate_delivery_intent_id": intent.id or False,
            "popup_completed_at": fields.Datetime.now(),
            "snoozed_until": False,
        }
        self.followup_id._write_from_workflow(values)
        self.followup_id._sync_reminder_delivery_intents()
        self._post_chatter_summary(event)
        self.env["bus.bus"].sudo()._sendone(
            self.followup_id.agent_id.partner_id,
            POST_CALL_BUS_CHANNEL,
            {
                "status": "completed",
                "followup_id": self.followup_id.id,
                "event_id": self.followup_id.event_id,
            },
        )
        return {"type": "ir.actions.act_window_close"}

    def action_complete_without_email(self):
        self.ensure_one()
        self.send_post_call_email = False
        return self.action_complete()
