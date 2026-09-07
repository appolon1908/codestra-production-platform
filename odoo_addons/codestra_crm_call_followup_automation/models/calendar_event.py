from odoo import api, models


class CalendarEventAutomation(models.Model):
    _inherit = "calendar.event"

    def write(self, values):
        tracked = bool({"start", "stop", "active"}.intersection(values))
        previous_starts = {event.id: event.start for event in self} if "start" in values else {}
        result = super().write(values)
        if "start" in values and not self.env.context.get("skip_codestra_followup_sync"):
            followups = self.filtered(
                lambda event: event.codestra_call_followup_id
                and event.start != previous_starts.get(event.id)
            ).mapped(
                "codestra_call_followup_id"
            )
            if followups:
                # A changed start is a new occurrence; old completion and
                # missed-callback evidence cannot suppress its SLA.
                followups._write_from_workflow({
                    "callback_completed_at": False,
                    "automation_missed_callback_at": False,
                })
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
