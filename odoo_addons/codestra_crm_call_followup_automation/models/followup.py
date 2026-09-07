from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class CodestraCrmCallFollowupAutomation(models.Model):
    _inherit = "codestra.crm.call.followup"

    automation_policy_id = fields.Many2one(
        "codestra.crm.call.followup.policy",
        compute="_compute_automation_policy_id",
        string="Automation policy",
    )
    automation_pending_sla_at = fields.Datetime(readonly=True, copy=False, index=True)
    automation_missed_callback_at = fields.Datetime(readonly=True, copy=False, index=True)
    callback_completed_at = fields.Datetime(readonly=True, copy=False, index=True)
    automation_reminders_repaired_at = fields.Datetime(readonly=True, copy=False)
    automation_last_job_at = fields.Datetime(readonly=True, copy=False)
    automation_exception_count = fields.Integer(readonly=True, copy=False, default=0)
    automation_job_ids = fields.One2many(
        "codestra.crm.call.followup.job",
        "followup_id",
        string="Automation jobs",
        readonly=True,
    )
    automation_job_count = fields.Integer(compute="_compute_automation_job_count")

    @api.depends("company_id")
    def _compute_automation_policy_id(self):
        Policy = self.env["codestra.crm.call.followup.policy"]
        cache = {}
        for record in self:
            company_id = record.company_id.id
            if company_id not in cache:
                cache[company_id] = Policy.policy_for_company(record.company_id)
            record.automation_policy_id = cache[company_id]

    @api.depends("automation_job_ids")
    def _compute_automation_job_count(self):
        for record in self:
            record.automation_job_count = len(record.automation_job_ids)

    def action_open_automation_jobs(self):
        self.ensure_one()
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(_("Call follow-up manager access is required."))
        action = self.env["ir.actions.actions"]._for_xml_id(
            "codestra_crm_call_followup_automation.action_call_followup_automation_job"
        )
        action.update(
            {
                "name": _("Automation jobs — %s") % self.display_name,
                "domain": [("followup_id", "=", self.id)],
                "context": {"default_followup_id": self.id},
            }
        )
        return action

    def action_retry_failed_automation(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(_("Call follow-up manager access is required."))
        # Search the durable queue directly. The one2many relation may have
        # been cached before a cron created the failed job in this transaction.
        jobs = self.env["codestra.crm.call.followup.job"].search([
            ("followup_id", "in", self.ids),
            ("state", "in", ["retry", "dead"]),
        ])
        for job in jobs.sudo():
            values = {
                "state": "pending",
                "next_attempt_at": fields.Datetime.now(),
                "last_error": False,
            }
            if job.state == "dead":
                # Preserve historical attempts while granting a complete new
                # policy-sized recovery window.
                values["max_attempts"] = job.attempt_count + job.policy_id.max_attempts
            job.write(values)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Automation retry queued"),
                "message": _("%s jobs were returned to the durable queue.") % len(jobs),
                "type": "success",
                "sticky": False,
            },
        }

    def action_mark_callback_completed(self):
        for record in self:
            if record.callback_completed_at:
                continue
            if not (
                self.env.user.has_group(
                    "codestra_crm_call_followup.group_call_followup_manager"
                )
                or record.agent_id == self.env.user
            ):
                raise AccessError(_("Only the assigned agent or a manager may complete callbacks."))
            if record.schedule_kind == "none" or not record.callback_at:
                raise AccessError(_("This follow-up has no scheduled callback to complete."))
            record._write_from_workflow({"callback_completed_at": fields.Datetime.now()})
        return True
