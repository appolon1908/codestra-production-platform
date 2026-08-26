from __future__ import annotations

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CodestraCrmPostCallWizardHardening(models.TransientModel):
    _inherit = "codestra.crm.post.call.wizard"

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        followup_id = values.get("followup_id") or self.env.context.get(
            "default_followup_id"
        )
        followup = self.env["codestra.crm.call.followup"].browse(
            followup_id
        ).exists()
        if followup:
            # Preserve an explicit agent choice to disable immediate email.
            values["send_post_call_email"] = followup.send_post_call_email
        return values

    def _lock_pending_followup(self):
        self.ensure_one()
        followup = self.followup_id.exists()
        if not followup:
            raise ValidationError(_("The call follow-up no longer exists."))
        self.env.cr.execute(
            f"SELECT state FROM {followup._table} WHERE id = %s FOR UPDATE",
            [followup.id],
        )
        row = self.env.cr.fetchone()
        if not row or row[0] != "pending":
            raise ValidationError(_("This call follow-up is no longer pending."))
        return followup

    def _validate_draft(self):
        self.ensure_one()
        if (
            self.disposition in {"do_not_call", "wrong_number"}
            and self.schedule_kind != "none"
        ):
            raise ValidationError(
                _("A do-not-call or wrong-number outcome cannot have an appointment.")
            )
        if self.schedule_kind != "none":
            if not self.callback_at:
                raise ValidationError(_("Choose a callback or appointment date and time."))
            if self.callback_at <= fields.Datetime.now():
                raise ValidationError(_("The callback or appointment must be in the future."))
            if not 5 <= self.duration_minutes <= 480:
                raise ValidationError(_("The duration must be between 5 and 480 minutes."))
        if self.email_to:
            self._validate_email_list(self.email_to, _("Recipient"), required=False)
        if self.email_cc:
            self._validate_email_list(self.email_cc, _("CC"), required=False)

    def _draft_values(self, *, snoozed_until=False):
        self.ensure_one()
        return {
            "disposition": self.disposition,
            "notes": self.notes,
            "schedule_kind": self.schedule_kind,
            "callback_at": self.callback_at if self.schedule_kind != "none" else False,
            "duration_minutes": self.duration_minutes,
            "reminder_email_enabled": self.reminder_email_enabled,
            "send_post_call_email": self.send_post_call_email,
            "email_to": self.email_to,
            "email_cc": self.email_cc,
            "email_subject": self.email_subject,
            "email_body": self.email_body,
            "draft_saved_at": fields.Datetime.now(),
            "snoozed_until": snoozed_until,
        }

    def _success_notification(self, title, message):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_save_draft(self):
        self.ensure_one()
        self._validate_draft()
        followup = self._lock_pending_followup()
        followup._write_from_workflow(self._draft_values())
        return self._success_notification(
            _("Draft saved"),
            _("Your post-call notes and preferences were saved without completing the call."),
        )

    def action_snooze_10_minutes(self):
        self.ensure_one()
        self._validate_draft()
        followup = self._lock_pending_followup()
        snoozed_until = fields.Datetime.now() + timedelta(minutes=10)
        followup._write_from_workflow(
            self._draft_values(snoozed_until=snoozed_until)
        )
        return self._success_notification(
            _("Follow-up snoozed"),
            _("The post-call form will become available again in 10 minutes."),
        )

    def _calendar_event_values(self):
        values = super()._calendar_event_values()
        values.update(
            {
                "active": True,
                "codestra_schedule_kind": self.schedule_kind,
            }
        )
        return values

    def action_complete(self):
        result = super().action_complete()
        completed = self.mapped("followup_id").filtered(
            lambda followup: followup.state == "completed"
        )
        if completed:
            completed._write_from_workflow({"snoozed_until": False})
        return result
