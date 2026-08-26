from odoo import api, fields, models


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    codestra_call_followup_id = fields.Many2one(
        "codestra.crm.call.followup",
        string="Call Follow-up",
        index=True,
        copy=False,
        ondelete="set null",
    )

    _codestra_followup_unique = models.Constraint(
        "UNIQUE(codestra_call_followup_id)",
        "A call follow-up can be linked to only one calendar event.",
    )

    def write(self, values):
        result = super().write(values)
        if self.env.context.get("skip_codestra_followup_sync"):
            return result

        if {"start", "stop", "active"}.intersection(values):
            for event in self.filtered("codestra_call_followup_id"):
                followup_values = {}
                if "start" in values:
                    followup_values["callback_at"] = event.start
                if {"start", "stop"}.intersection(values) and event.start and event.stop:
                    duration = int(
                        max(1, round((event.stop - event.start).total_seconds() / 60))
                    )
                    followup_values["duration_minutes"] = duration
                if "active" in values and not event.active:
                    followup_values.update(
                        {
                            "schedule_kind": "none",
                            "callback_at": False,
                            "calendar_event_id": False,
                        }
                    )
                if followup_values:
                    event.codestra_call_followup_id.with_context(
                        skip_codestra_calendar_sync=True
                    ).write(followup_values)
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_sync_call_followup(self):
        if self.env.context.get("skip_codestra_followup_sync"):
            return
        followups = self.mapped("codestra_call_followup_id")
        if followups:
            followups.with_context(skip_codestra_calendar_sync=True).write(
                {
                    "schedule_kind": "none",
                    "callback_at": False,
                    "calendar_event_id": False,
                }
            )
