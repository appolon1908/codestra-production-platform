from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class CodestraCrmCallFollowupAutomationApi(models.AbstractModel):
    _name = "codestra.crm.call.followup.automation.api"
    _description = "CRM Call Follow-up Automation API"

    @api.model
    def capabilities_v1(self):
        return {
            "api_version": "1.0",
            "features": [
                "pending-followup-sla",
                "missed-callback-escalation",
                "calendar-reminder-repair",
                "idempotent-job-enqueue",
                "skip-locked-workers",
                "bounded-exponential-retry",
                "dead-letter-visibility",
            ],
        }

    @api.model
    def _require_manager(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(_("Call follow-up manager access is required."))

    @api.model
    def health_v1(self, company_ids=None):
        self._require_manager()
        allowed = set(self.env.user.company_ids.ids)
        requested = set(int(item) for item in (company_ids or allowed))
        company_ids = sorted(allowed & requested)
        Job = self.env["codestra.crm.call.followup.job"]
        domain = [("company_id", "in", company_ids)]
        return {
            "api_version": "1.0",
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
            "company_ids": company_ids,
            "pending": Job.search_count(domain + [("state", "=", "pending")]),
            "running": Job.search_count(domain + [("state", "=", "running")]),
            "retry": Job.search_count(domain + [("state", "=", "retry")]),
            "dead": Job.search_count(domain + [("state", "=", "dead")]),
            "done": Job.search_count(domain + [("state", "=", "done")]),
        }

    @api.model
    def run_once_v1(self, company_ids=None, limit=100):
        self._require_manager()
        allowed = set(self.env.user.company_ids.ids)
        requested = set(int(item) for item in (company_ids or allowed))
        company_ids = sorted(allowed & requested)
        Job = self.env["codestra.crm.call.followup.job"]
        created = Job._cron_enqueue_due_jobs(company_ids=company_ids)
        processed = Job._cron_process_jobs(limit=limit)
        return {
            "api_version": "1.0",
            "queued": created,
            "processed": processed,
            "health": self.health_v1(company_ids),
        }
