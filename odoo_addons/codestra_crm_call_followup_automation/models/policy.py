from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CodestraCrmCallFollowupPolicy(models.Model):
    _name = "codestra.crm.call.followup.policy"
    _description = "CRM Call Follow-up Automation Policy"
    _inherit = ["mail.thread"]
    _order = "company_id, id"

    name = fields.Char(required=True, default="Call Follow-up Automation", tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete="cascade",
        tracking=True,
    )
    pending_sla_minutes = fields.Integer(
        default=10,
        required=True,
        tracking=True,
        help="Create an escalation activity when an agent has not completed the post-call action within this period.",
    )
    callback_grace_minutes = fields.Integer(
        default=15,
        required=True,
        tracking=True,
        help="A callback is considered missed after its scheduled time plus this grace period.",
    )
    max_attempts = fields.Integer(default=5, required=True, tracking=True)
    retry_base_minutes = fields.Integer(default=2, required=True, tracking=True)
    create_pending_activity = fields.Boolean(default=True, tracking=True)
    create_missed_callback_activity = fields.Boolean(default=True, tracking=True)
    repair_calendar_reminders = fields.Boolean(default=True, tracking=True)
    escalation_user_id = fields.Many2one(
        "res.users",
        string="Escalation owner",
        domain=[("share", "=", False)],
        tracking=True,
        ondelete="set null",
    )
    activity_type_id = fields.Many2one(
        "mail.activity.type",
        required=True,
        default=lambda self: self.env.ref("mail.mail_activity_data_todo"),
        ondelete="restrict",
        tracking=True,
    )
    notes = fields.Html(sanitize=True)

    _company_unique = models.Constraint(
        "UNIQUE(company_id)",
        "Only one call follow-up automation policy is allowed per company.",
    )

    @api.constrains(
        "pending_sla_minutes",
        "callback_grace_minutes",
        "max_attempts",
        "retry_base_minutes",
    )
    def _check_ranges(self):
        for policy in self:
            if not 1 <= policy.pending_sla_minutes <= 1440:
                raise ValidationError(_("Pending SLA must be between 1 and 1,440 minutes."))
            if not 0 <= policy.callback_grace_minutes <= 1440:
                raise ValidationError(_("Callback grace must be between 0 and 1,440 minutes."))
            if not 1 <= policy.max_attempts <= 20:
                raise ValidationError(_("Maximum attempts must be between 1 and 20."))
            if not 1 <= policy.retry_base_minutes <= 60:
                raise ValidationError(_("Retry base must be between 1 and 60 minutes."))

    @api.model
    def policy_for_company(self, company):
        return self.sudo().search(
            [("company_id", "=", company.id), ("active", "=", True)],
            limit=1,
        )

    def action_run_automation_now(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(_("Call follow-up manager access is required."))
        created = self.env["codestra.crm.call.followup.job"]._cron_enqueue_due_jobs(
            company_ids=self.mapped("company_id").ids
        )
        processed = self.env["codestra.crm.call.followup.job"]._cron_process_jobs()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Call follow-up automation completed"),
                "message": _("%s jobs were queued and %s jobs were processed.")
                % (created, processed),
                "type": "success",
                "sticky": False,
            },
        }
