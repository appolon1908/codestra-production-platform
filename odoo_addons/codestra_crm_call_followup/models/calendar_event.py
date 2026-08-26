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

        watched = {"start", "stop", "active", "location"}
        if not watched.intersection(values):
            return result

        for event in self.filtered("codestra_call_followup_id"):
            followup_values = {}
            if "start" in values:
                followup_values["callback_at"] = event.start
            if {"start", "stop"}.intersection(values) and event.start and event.stop:
                followup_values["duration_minutes"] = int(
                    max(
                        1,
                        round(
                            (event.stop - event.start).total_seconds()
                            / 60
                        ),
                    )
                )
            if "location" in values:
                followup_values["meeting_location"] = event.location or False
            if "active" in values and not event.active:
                followup_values.update(
                    {
                        "schedule_kind": "none",
                        "callback_at": False,
                        "calendar_event_id": False,
                        "meeting_location": False,
                    }
                )
            if followup_values:
                event.codestra_call_followup_id._write_from_workflow(
                    followup_values
                )
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_sync_call_followup(self):
        if self.env.context.get("skip_codestra_followup_sync"):
            return
        followups = self.mapped("codestra_call_followup_id")
        if followups:
            followups._write_from_workflow(
                {
                    "schedule_kind": "none",
                    "callback_at": False,
                    "calendar_event_id": False,
                    "meeting_location": False,
                }
            )
