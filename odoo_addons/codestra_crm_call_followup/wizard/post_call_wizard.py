from __future__ import annotations

from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tools import email_split

from ..models.call_followup import (
    COMPLIANCE_REVIEW_DISPOSITIONS,
    CONTACT_CHANNEL_SELECTION,
    DISPOSITION_SELECTION,
    PRIORITY_SELECTION,
    SCHEDULE_KIND_SELECTION,
    SENTIMENT_SELECTION,
)


NOTES_REQUIRED_DISPOSITIONS = {
    "do_not_call",
    "wrong_number",
    "not_interested",
    "other",
}


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
        related="followup_id.duration_seconds", readonly=True
    )
    call_duration_display = fields.Char(
        compute="_compute_call_duration_display", readonly=True
    )
    followup_state = fields.Selection(related="followup_id.state", readonly=True)

    disposition = fields.Selection(DISPOSITION_SELECTION, required=True)
    notes = fields.Html(sanitize=True)
    priority = fields.Selection(
        PRIORITY_SELECTION, required=True, default="normal"
    )
    customer_sentiment = fields.Selection(SENTIMENT_SELECTION)

    schedule_kind = fields.Selection(
        SCHEDULE_KIND_SELECTION, required=True, default="none"
    )
    callback_at = fields.Datetime(string="Date and Time")
    duration_minutes = fields.Integer(default=30)
    contact_channel = fields.Selection(
        CONTACT_CHANNEL_SELECTION, required=True, default="phone"
    )
    meeting_location = fields.Char(string="Location or Meeting Link")
    reminder_email_enabled = fields.Boolean(
        string="Email client and agent 15 minutes before", default=True
    )

    send_post_call_email = fields.Boolean(
        string="Send follow-up email now", default=True
    )
    email_to = fields.Char(string="To")
    email_cc = fields.Char(string="CC")
    email_subject = fields.Char(string="Subject")
    email_body = fields.Html(string="Email", sanitize=True)

    @api.depends("call_duration_seconds")
    def _compute_call_duration_display(self):
        for wizard in self:
            total = max(0, wizard.call_duration_seconds or 0)
            hours, remainder = divmod(total, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                wizard.call_duration_display = _(
                    "%(hours)sh %(minutes)sm %(seconds)ss"
                ) % {"hours": hours, "minutes": minutes, "seconds": seconds}
            elif minutes:
                wizard.call_duration_display = _(
                    "%(minutes)sm %(seconds)ss"
                ) % {"minutes": minutes, "seconds": seconds}
            else:
                wizard.call_duration_display = _("%ss") % seconds

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        followup_id = (
            values.get("followup_id")
            or self.env.context.get("default_followup_id")
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
                "priority": followup.priority or "normal",
                "customer_sentiment": followup.customer_sentiment,
                "schedule_kind": followup.schedule_kind or "none",
                "callback_at": followup.callback_at,
                "duration_minutes": followup.duration_minutes or 30,
                "contact_channel": followup.contact_channel or "phone",
                "meeting_location": followup.meeting_location,
                "reminder_email_enabled": followup.reminder_email_enabled,
                "send_post_call_email": bool(followup.email_to),
                "email_to": followup.email_to,
                "email_cc": followup.email_cc or followup.agent_id.email,
                "email_subject": followup.email_subject,
                "email_body": followup.email_body,
            }
        )
        if not values.get("email_subject") or not values.get("email_body"):
            generated = self._render_default_email(followup)
            values["email_subject"] = (
                values.get("email_subject") or generated.get("subject")
            )
            values["email_body"] = (
                values.get("email_body") or generated.get("body_html")
            )
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
            [followup.id], ["subject", "body_html"]
        )
        return rendered.get(followup.id, {})

    @api.onchange("schedule_kind")
    def _onchange_schedule_kind(self):
        if self.schedule_kind == "none":
            self.callback_at = False
            self.meeting_location = False
            return
        if not self.callback_at:
            self.callback_at = fields.Datetime.now() + timedelta(hours=1)
        if self.schedule_kind == "callback":
            self.disposition = "callback"
            self.contact_channel = "phone"
        elif self.schedule_kind == "appointment":
            self.disposition = "appointment"
            if self.contact_channel == "phone":
                self.contact_channel = "video"

    @api.onchange("contact_channel")
    def _onchange_contact_channel(self):
        if self.contact_channel == "phone":
            self.meeting_location = False

    @api.onchange("disposition")
    def _onchange_disposition(self):
        if self.disposition in COMPLIANCE_REVIEW_DISPOSITIONS:
            self.schedule_kind = "none"
            self.callback_at = False
            self.send_post_call_email = False
            self.reminder_email_enabled = False

    @api.onchange("send_post_call_email")
    def _onchange_send_post_call_email(self):
        if self.send_post_call_email and not self.email_to:
            self.email_to = (
                self.followup_id.partner_id.email
                or self.followup_id.lead_id.email_from
                or False
            )

    def _validate_email_list(self, value, label, *, required=False):
        normalized = (value or "").strip()
        if not normalized:
            if required:
                raise ValidationError(_("%s is required.") % label)
            return
        if not email_split(normalized):
            raise ValidationError(
                _("%s does not contain a valid email address.") % label
            )

    def _validate_completion(self):
        self.ensure_one()
        if not self.disposition:
            raise ValidationError(_("Select a call outcome."))
        if self.disposition in NOTES_REQUIRED_DISPOSITIONS and not self.notes:
            raise ValidationError(
                _(
                    "Add notes for this outcome so the CRM and compliance "
                    "history is complete."
                )
            )
        if (
            self.disposition in COMPLIANCE_REVIEW_DISPOSITIONS
            and self.schedule_kind != "none"
        ):
            raise ValidationError(
                _("A do-not-call or wrong-number outcome cannot have an appointment.")
            )
        if (
            self.disposition in COMPLIANCE_REVIEW_DISPOSITIONS
            and self.send_post_call_email
        ):
            raise ValidationError(
                _(
                    "Do-not-call and wrong-number outcomes cannot queue "
                    "an automatic follow-up email."
                )
            )

        if self.send_post_call_email:
            self._validate_email_list(
                self.email_to, _("Recipient"), required=True
            )
            self._validate_email_list(self.email_cc, _("CC"))
            if not (self.email_subject or "").strip():
                raise ValidationError(_("The email subject is required."))
            if not self.email_body:
                raise ValidationError(_("The email body is required."))

        if self.schedule_kind == "none":
            return
        if not self.callback_at:
            raise ValidationError(
                _("Choose a callback or appointment date and time.")
            )
        if self.callback_at <= fields.Datetime.now():
            raise ValidationError(
                _("The callback or appointment must be in the future.")
            )
        if not 5 <= self.duration_minutes <= 480:
            raise ValidationError(
                _("The duration must be between 5 and 480 minutes.")
            )
        if (
            self.contact_channel in {"video", "in_person"}
            and not (self.meeting_location or "").strip()
        ):
            raise ValidationError(
                _("Add the meeting link or physical location for this contact method.")
            )

        if self.reminder_email_enabled:
            client = (
                self.followup_id.partner_id
                or self.followup_id.lead_id.partner_id
            )
            if not client:
                raise ValidationError(
                    _(
                        "Link the CRM lead to a customer/contact before "
                        "enabling client reminders."
                    )
                )
            self._validate_email_list(
                client.email, _("Client email"), required=True
            )
            self._validate_email_list(
                self.followup_id.agent_id.email,
                _("Agent email"),
                required=True,
            )

    def _calendar_alarm_ids(self):
        alarms = [
            self.env.ref(
                "codestra_crm_call_followup."
                "calendar_alarm_prepare_30_minutes"
            ).id
        ]
        if self.reminder_email_enabled:
            alarms.append(
                self.env.ref(
                    "codestra_crm_call_followup."
                    "calendar_alarm_email_15_minutes"
                ).id
            )
        return alarms

    def _calendar_event_values(self, followup):
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
        description = Markup("<p><strong>%s</strong></p>") % _(
            "Prepared from the completed-call CRM workflow."
        )
        description += (
            Markup(self.notes)
            if self.notes
            else Markup("<p>%s</p>") % _("No additional notes.")
        )
        location = (
            (self.meeting_location or "").strip()
            or (
                _("Phone callback")
                if self.contact_channel == "phone"
                else False
            )
        )
        return {
            "name": title,
            "start": self.callback_at,
            "stop": self.callback_at
            + timedelta(minutes=self.duration_minutes),
            "user_id": followup.agent_id.id,
            "partner_ids": [
                Command.set(
                    (client | followup.agent_id.partner_id).ids
                )
            ],
            "alarm_ids": [Command.set(self._calendar_alarm_ids())],
            "description": description,
            "location": location,
            "privacy": "private",
            "codestra_call_followup_id": followup.id,
        }

    def _schedule_or_remove_calendar_event(self, followup):
        event = followup.calendar_event_id
        if self.schedule_kind == "none":
            if event:
                event.with_context(
                    skip_codestra_followup_sync=True,
                    mail_notify_force_send=False,
                ).unlink()
            return self.env["calendar.event"].browse()

        values = self._calendar_event_values(followup)
        if event:
            event.with_context(
                skip_codestra_followup_sync=True
            ).write(values)
            return event
        return self.env["calendar.event"].create(values)

    def _queue_post_call_email(self, followup):
        if not self.send_post_call_email:
            return self.env["mail.mail"].browse()
        template = self.env.ref(
            "codestra_crm_call_followup.mail_template_post_call_followup"
        ).sudo()
        sender = (
            followup.agent_id.email_formatted
            or followup.company_id.email_formatted
            or self.env.user.email_formatted
        )
        email_values = {
            "email_to": self.email_to.strip(),
            "email_cc": (self.email_cc or "").strip() or False,
            "author_id": followup.agent_id.partner_id.id,
            "subject": self.email_subject.strip(),
            "body_html": self.email_body,
        }
        if sender:
            email_values["email_from"] = sender
        mail_id = template.send_mail(
            followup.id,
            force_send=False,
            raise_exception=True,
            email_values=email_values,
        )
        return self.env["mail.mail"].sudo().browse(mail_id)

    def _post_chatter_summary(self, followup, event):
        if not followup.lead_id:
            return
        disposition = dict(DISPOSITION_SELECTION).get(
            self.disposition, self.disposition
        )
        priority = dict(PRIORITY_SELECTION).get(
            self.priority, self.priority
        )
        sentiment = dict(SENTIMENT_SELECTION).get(
            self.customer_sentiment,
            self.customer_sentiment or _("Not recorded"),
        )
        schedule = _("No callback scheduled")
        if event:
            schedule = _(
                "%(kind)s scheduled for %(date)s via %(channel)s"
            ) % {
                "kind": dict(SCHEDULE_KIND_SELECTION).get(
                    self.schedule_kind, self.schedule_kind
                ),
                "date": fields.Datetime.to_string(self.callback_at),
                "channel": dict(CONTACT_CHANNEL_SELECTION).get(
                    self.contact_channel, self.contact_channel
                ),
            }
        body = Markup(
            "<p><strong>%s</strong></p>"
            "<p>%s: %s<br/>%s: %s<br/>%s: %s<br/>%s</p>"
        ) % (
            _("Post-call follow-up completed"),
            _("Outcome"),
            disposition,
            _("Priority"),
            priority,
            _("Customer sentiment"),
            sentiment,
            schedule,
        )
        if self.disposition in COMPLIANCE_REVIEW_DISPOSITIONS:
            body += (
                Markup('<p class="text-danger"><strong>%s</strong></p>')
                % _("Compliance review required")
            )
        if self.notes:
            body += Markup("<p><strong>%s</strong></p>") % _("Agent notes")
            body += Markup(self.notes)
        followup.lead_id.message_post(
            body=body, subtype_xmlid="mail.mt_note"
        )

    def _draft_values(self):
        values = {
            "disposition": self.disposition,
            "notes": self.notes,
            "priority": self.priority,
            "customer_sentiment": self.customer_sentiment,
            "send_post_call_email": self.send_post_call_email,
            "email_to": self.email_to,
            "email_cc": self.email_cc,
            "email_subject": self.email_subject,
            "email_body": self.email_body,
        }
        if self.schedule_kind != "none" and self.callback_at:
            values.update(
                {
                    "schedule_kind": self.schedule_kind,
                    "callback_at": self.callback_at,
                    "duration_minutes": self.duration_minutes,
                    "contact_channel": self.contact_channel,
                    "meeting_location": self.meeting_location,
                    "reminder_email_enabled": self.reminder_email_enabled,
                }
            )
        else:
            values.update({"schedule_kind": "none", "callback_at": False})
        return values

    def action_complete(self):
        self.ensure_one()
        followup = self.followup_id._lock_for_completion()
        if followup.state == "completed":
            return {"type": "ir.actions.act_window_close"}
        if followup.state != "pending":
            raise ValidationError(
                _("This post-call action is no longer pending.")
            )

        self._validate_completion()
        event = self._schedule_or_remove_calendar_event(followup)
        mail = self._queue_post_call_email(followup)
        now = fields.Datetime.now()
        followup._write_from_workflow(
            {
                "state": "completed",
                "disposition": self.disposition,
                "notes": self.notes,
                "priority": self.priority,
                "customer_sentiment": self.customer_sentiment,
                "compliance_review_required": (
                    self.disposition in COMPLIANCE_REVIEW_DISPOSITIONS
                ),
                "schedule_kind": self.schedule_kind,
                "callback_at": (
                    self.callback_at
                    if self.schedule_kind != "none"
                    else False
                ),
                "duration_minutes": self.duration_minutes,
                "contact_channel": self.contact_channel,
                "meeting_location": (
                    self.meeting_location
                    if self.schedule_kind != "none"
                    else False
                ),
                "calendar_event_id": event.id or False,
                "reminder_email_enabled": self.reminder_email_enabled,
                "send_post_call_email": self.send_post_call_email,
                "email_to": self.email_to,
                "email_cc": self.email_cc,
                "email_subject": self.email_subject,
                "email_body": self.email_body,
                "mail_id": mail.id or False,
                "snoozed_until": False,
                "popup_completed_at": now,
                "completed_at": now,
                "completed_by_id": self.env.user.id,
            }
        )
        self._post_chatter_summary(followup, event)
        return {"type": "ir.actions.act_window_close"}

    def action_complete_without_email(self):
        self.ensure_one()
        self.send_post_call_email = False
        return self.action_complete()

    def action_snooze_10_minutes(self):
        self.ensure_one()
        followup = self.followup_id._lock_for_completion()
        if followup.state != "pending":
            raise ValidationError(
                _("Only pending post-call actions can be snoozed.")
            )
        values = self._draft_values()
        values["snoozed_until"] = (
            fields.Datetime.now() + timedelta(minutes=10)
        )
        followup._write_from_workflow(values)
        return {"type": "ir.actions.act_window_close"}

    def action_open_related_record(self):
        self.ensure_one()
        return self.followup_id.action_open_related_record()
