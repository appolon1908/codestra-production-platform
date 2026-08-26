from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CodestraCrmPostCallWizardWorkspace(models.TransientModel):
    _inherit = "codestra.crm.post.call.wizard"

    ux_partner_id = fields.Many2one(
        "res.partner",
        related="followup_id.partner_id",
        readonly=True,
    )
    ux_lead_id = fields.Many2one(
        "crm.lead",
        related="followup_id.lead_id",
        readonly=True,
    )
    ux_calendar_event_id = fields.Many2one(
        "calendar.event",
        related="followup_id.calendar_event_id",
        readonly=True,
    )
    ux_contact_label = fields.Char(
        related="followup_id.ux_contact_label",
        readonly=True,
    )
    ux_call_duration_label = fields.Char(
        related="followup_id.ux_call_duration_label",
        readonly=True,
    )
    ux_schedule_ready = fields.Boolean(compute="_compute_ux_readiness")
    ux_email_ready = fields.Boolean(compute="_compute_ux_readiness")
    ux_ready = fields.Boolean(compute="_compute_ux_readiness")
    ux_completion_guidance = fields.Html(
        compute="_compute_ux_readiness",
        sanitize=True,
    )

    @api.depends(
        "schedule_kind",
        "callback_at",
        "duration_minutes",
        "send_post_call_email",
        "email_to",
        "email_subject",
        "email_body",
        "disposition",
    )
    def _compute_ux_readiness(self):
        for wizard in self:
            wizard.ux_schedule_ready = bool(
                wizard.schedule_kind == "none"
                or (
                    wizard.callback_at
                    and wizard.duration_minutes
                    and wizard.duration_minutes > 0
                )
            )
            wizard.ux_email_ready = bool(
                not wizard.send_post_call_email
                or (
                    (wizard.email_to or "").strip()
                    and (wizard.email_subject or "").strip()
                    and wizard.email_body
                )
            )
            wizard.ux_ready = bool(
                wizard.disposition
                and wizard.ux_schedule_ready
                and wizard.ux_email_ready
            )
            messages = []
            if not wizard.disposition:
                messages.append(_("Choose a call outcome."))
            if not wizard.ux_schedule_ready:
                messages.append(
                    _("Choose a valid future date, time, and duration.")
                )
            if not wizard.ux_email_ready:
                messages.append(
                    _(
                        "Add a recipient, subject, and message or turn off the immediate email."
                    )
                )
            if messages:
                wizard.ux_completion_guidance = (
                    "<strong>%s</strong><ul>%s</ul>"
                    % (
                        _("Before completing"),
                        "".join(
                            "<li>%s</li>" % message
                            for message in messages
                        ),
                    )
                )
            else:
                wizard.ux_completion_guidance = (
                    "<strong>%s</strong><br/>%s"
                    % (
                        _("Ready to save"),
                        _(
                            "The outcome, next step, notes, reminders, and email choices will be committed together."
                        ),
                    )
                )

    def action_ux_open_customer(self):
        self.ensure_one()
        return self.followup_id.action_ux_open_customer()

    def action_ux_open_opportunity(self):
        self.ensure_one()
        return self.followup_id.action_ux_open_opportunity()

    def action_ux_open_calendar(self):
        self.ensure_one()
        return self.followup_id.action_ux_open_calendar()

    def action_ux_complete_without_email(self):
        self.ensure_one()
        self.send_post_call_email = False
        return self.action_complete()

    def action_ux_complete_and_open_calendar(self):
        self.ensure_one()
        if self.schedule_kind == "none":
            raise UserError(
                _(
                    "Choose Callback or Appointment before using this action."
                )
            )
        followup = self.followup_id
        self.action_complete()
        followup.invalidate_recordset(["calendar_event_id"])
        return followup.action_ux_open_calendar()

    def action_ux_complete_and_open_customer(self):
        self.ensure_one()
        followup = self.followup_id
        self.action_complete()
        return followup.action_ux_open_customer()
