from odoo import _, api, fields, models

from odoo.addons.codestra_crm_call_followup.models.call_followup import (
    POST_CALL_BUS_CHANNEL,
)


class CodestraCrmCallFollowupUxHardening(models.Model):
    """Serialize snooze release so one due item emits one popup."""

    _inherit = "codestra.crm.call.followup"

    @api.model
    def _cron_release_snoozed_followups(self, batch_size=500):
        try:
            batch_size = max(1, min(int(batch_size), 2000))
        except (TypeError, ValueError):
            batch_size = 500

        # The selection below is raw SQL and must observe pending ORM writes
        # made earlier in the same transaction, including tests and manual
        # snooze actions.
        self.flush_model(["state", "popup_completed_at", "snoozed_until"])
        now = fields.Datetime.now()
        self.env.cr.execute(
            f"""
                SELECT id
                  FROM {self._table}
                 WHERE state = 'pending'
                   AND popup_completed_at IS NULL
                   AND snoozed_until IS NOT NULL
                   AND snoozed_until <= %s
                 ORDER BY snoozed_until ASC, id ASC
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
            """,
            [now, batch_size],
        )
        records = self.sudo().browse(
            [row[0] for row in self.env.cr.fetchall()]
        ).exists()

        for record in records:
            record._write_from_workflow(
                {
                    "snoozed_until": False,
                    "last_popup_released_at": now,
                }
            )
            self.env["bus.bus"].sudo()._sendone(
                record.agent_id.partner_id,
                POST_CALL_BUS_CHANNEL,
                {
                    "followup_id": record.id,
                    "event_id": record.event_id,
                    "title": _("Post-call reminder"),
                    "message": _(
                        "Your snoozed post-call action is ready."
                    ),
                },
            )
        return len(records)
