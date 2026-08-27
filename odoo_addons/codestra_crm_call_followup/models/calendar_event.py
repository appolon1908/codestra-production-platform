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

    def _codestra_linked_events(self, values=None):
        linked = self.filtered("codestra_call_followup_id")
        if values and values.get("codestra_call_followup_id"):
            linked |= self
        return linked

    def _codestra_no_mail(self):
        return self.with_context(
            no_mail_to_attendees=True,
            mail_notify_force_send=False,
        )

    def write(self, values):
        # Suppress native attendee email only for Codestra call events. Ordinary
        # Odoo calendar events retain standard invitation behavior.
        linked = self._codestra_linked_events(values)
        ordinary = self - linked
        result = True
        if ordinary:
            result = super(CalendarEvent, ordinary).write(values) and result
        if linked:
            protected = linked._codestra_no_mail()
            result = super(CalendarEvent, protected).write(values) and result

        if not linked or self.env.context.get("skip_codestra_followup_sync"):
            return result

        if {"start", "stop", "active", "codestra_schedule_kind"}.intersection(values):
            for event in linked.filtered("codestra_call_followup_id"):
                followup = event.codestra_call_followup_id
                followup_values = {}

                if "active" in values and not event.active:
                    # Rows created by 19.0.1.0.0 can have a null event-side
                    # schedule kind. Preserve the authoritative follow-up kind
                    # before clearing the active schedule.
                    preserved_kind = event.codestra_schedule_kind
                    if (
                        not preserved_kind
                        and followup.schedule_kind in {"callback", "appointment"}
                    ):
                        preserved_kind = followup.schedule_kind
                        super(
                            CalendarEvent,
                            event.with_context(
                                skip_codestra_followup_sync=True,
                                no_mail_to_attendees=True,
                                mail_notify_force_send=False,
                            ),
                        ).write({"codestra_schedule_kind": preserved_kind})
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
                            max(
                                1,
                                round(
                                    (event.stop - event.start).total_seconds() / 60
                                ),
                            )
                        )
                    restored_kind = event.codestra_schedule_kind
                    if (
                        not restored_kind
                        and followup.schedule_kind in {"callback", "appointment"}
                    ):
                        restored_kind = followup.schedule_kind
                    if restored_kind:
                        followup_values["schedule_kind"] = restored_kind
                    followup_values["calendar_event_id"] = event.id

                if followup_values:
                    followup._write_from_workflow(followup_values)
                    followup._sync_reminder_delivery_intents()
        return result

    def unlink(self):
        linked = self.filtered("codestra_call_followup_id")
        ordinary = self - linked
        result = True
        if ordinary:
            result = super(CalendarEvent, ordinary).unlink() and result
        if linked:
            result = super(CalendarEvent, linked._codestra_no_mail()).unlink() and result
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
            followups._sync_reminder_delivery_intents()
