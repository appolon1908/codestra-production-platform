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
    codestra_schedule_kind = fields.Selection(
        [("callback", "Callback"), ("appointment", "Appointment")],
        string="Call Follow-up Schedule Type",
        copy=False,
    )

    _codestra_followup_unique = models.Constraint(
        "UNIQUE(codestra_call_followup_id)",
        "A call follow-up can be linked to only one calendar event.",
    )

    def init(self):
        """Backfill events created before codestra_schedule_kind existed."""
        self.env.cr.execute(
            """
            UPDATE calendar_event AS event
               SET codestra_schedule_kind = followup.schedule_kind
              FROM codestra_crm_call_followup AS followup
             WHERE event.codestra_call_followup_id = followup.id
               AND event.codestra_schedule_kind IS NULL
               AND followup.schedule_kind IN ('callback', 'appointment')
            """
        )

    def write(self, values):
        previous_kinds = {
            event.id: (
                event.codestra_schedule_kind
                or event.codestra_call_followup_id.schedule_kind
            )
            for event in self.filtered("codestra_call_followup_id")
        }
        result = super().write(values)
        if self.env.context.get("skip_codestra_followup_sync"):
            return result

        if {"start", "stop", "active", "codestra_schedule_kind"}.intersection(values):
            for event in self.filtered("codestra_call_followup_id"):
                previous_kind = previous_kinds.get(event.id)
                if (
                    "active" in values
                    and not event.active
                    and not event.codestra_schedule_kind
                    and previous_kind in {"callback", "appointment"}
                ):
                    # Persist the old schedule type before clearing the active CRM
                    # schedule. This also covers events created before the field was
                    # introduced when an upgrade backfill has not run yet.
                    event.with_context(skip_codestra_followup_sync=True).write(
                        {"codestra_schedule_kind": previous_kind}
                    )

                followup_values = {}
                if "active" in values and not event.active:
                    # Preserve the link to the archived event. This retains audit
                    # history and allows the same event to be safely reactivated.
                    followup_values.update(
                        {
                            "schedule_kind": "none",
                            "callback_at": False,
                        }
                    )
                elif event.active:
                    if event.start:
                        followup_values["callback_at"] = event.start
                    if event.start and event.stop:
                        followup_values["duration_minutes"] = int(
                            max(1, round((event.stop - event.start).total_seconds() / 60))
                        )
                    restored_kind = event.codestra_schedule_kind or previous_kind
                    if restored_kind in {"callback", "appointment"}:
                        followup_values["schedule_kind"] = restored_kind
                    followup_values["calendar_event_id"] = event.id

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
                }
            )
