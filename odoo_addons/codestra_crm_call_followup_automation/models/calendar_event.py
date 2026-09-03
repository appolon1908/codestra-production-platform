from odoo import api, models


class CalendarEventAutomation(models.Model):
    _inherit = "calendar.event"

    def write(self, values):
        tracked = bool({"start", "stop", "active"}.intersection(values))
        result = super().write(values)
        if (
            tracked
            and not self.env.context.get(
                "skip_codestra_automation_outbox"
            )
        ):
            outbox = self.env[
                "codestra.crm.call.followup.outbox"
            ]
            for event in self.filtered(
                "codestra_call_followup_id"
            ):
                event_type = (
                    "calendar.cancelled"
                    if not event.active
                    else "calendar.rescheduled"
                )
                outbox.enqueue_calendar_event(
                    event, event_type
                )
        return result

    @api.ondelete(at_uninstall=False)
    def _enqueue_calendar_cancellation(self):
        if self.env.context.get(
            "skip_codestra_automation_outbox"
        ):
            return
        outbox = self.env[
            "codestra.crm.call.followup.outbox"
        ]
        for event in self.filtered(
            "codestra_call_followup_id"
        ):
            outbox.enqueue_calendar_event(
                event, "calendar.cancelled"
            )
