from odoo import models


class CodestraCrmPostCallWizardAutomation(models.TransientModel):
    _inherit = "codestra.crm.post.call.wizard"

    def action_complete(self):
        self.ensure_one()
        followup = self.followup_id
        # Claim before invoking the inherited completion so this extension can
        # distinguish the winning transition from stale/concurrent submissions.
        if not self._claim_pending_followup():
            return {"type": "ir.actions.act_window_close"}
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
            followup._write_from_workflow({"callback_completed_at": False})
            self.env[
                "codestra.crm.call.followup.outbox"
            ].enqueue_followup_events(followup)
        return result
