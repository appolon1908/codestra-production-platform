from odoo import models


class CodestraCrmPostCallWizardAutomation(models.TransientModel):
    _inherit = "codestra.crm.post.call.wizard"

    def action_complete(self):
        self.ensure_one()
        followup = self.followup_id
        result = super().action_complete()
        followup.invalidate_recordset(
            [
                "state",
                "disposition",
                "schedule_kind",
                "callback_at",
                "calendar_event_id",
                "mail_id",
            ]
        )
        if followup.exists() and followup.state == "completed":
            self.env[
                "codestra.crm.call.followup.outbox"
            ].enqueue_followup_events(followup)
        return result
