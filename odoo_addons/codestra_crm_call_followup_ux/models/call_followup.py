from __future__ import annotations

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.codestra_crm_call_followup.models.call_followup import (
    POST_CALL_BUS_CHANNEL,
)


ALLOWED_SNOOZE_MINUTES = frozenset({5, 15, 30})


class CodestraCrmCallFollowupUx(models.Model):
    _inherit = "codestra.crm.call.followup"

    snoozed_until = fields.Datetime(
        index=True,
        tracking=True,
        copy=False,
    )
    snooze_count = fields.Integer(
        readonly=True,
        copy=False,
        default=0,
    )
    last_snoozed_at = fields.Datetime(readonly=True, copy=False)
    last_popup_released_at = fields.Datetime(readonly=True, copy=False)

    _snooze_count_non_negative = models.Constraint(
        "CHECK(snooze_count >= 0)",
        "The snooze count cannot be negative.",
    )

    def _assert_agent_workflow_access(self):
        manager = self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        )
        for record in self:
            if not manager and record.agent_id != self.env.user:
                raise AccessError(
                    _(
                        "Only the assigned agent or a call-follow-up manager "
                        "may perform this action."
                    )
                )

    def _snooze_for(self, minutes):
        """Persist a snooze without deciding how the caller's window behaves."""
        self.ensure_one()
        self._assert_agent_workflow_access()
        try:
            minutes = int(minutes)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                _("The snooze duration must be an integer.")
            ) from exc
        if minutes not in ALLOWED_SNOOZE_MINUTES:
            raise ValidationError(_("Choose a supported snooze duration."))
        if self.state != "pending" or self.popup_completed_at:
            raise ValidationError(
                _("Only an unfinished post-call action can be snoozed.")
            )

        now = fields.Datetime.now()
        self._write_from_workflow(
            {
                "snoozed_until": now + timedelta(minutes=minutes),
                "snooze_count": self.snooze_count + 1,
                "last_snoozed_at": now,
            }
        )
        return True

    def _snooze_and_reload(self, minutes):
        self.ensure_one()
        self._snooze_for(minutes)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_snooze_5(self):
        self.ensure_one()
        return self._snooze_and_reload(5)

    def action_snooze_15(self):
        self.ensure_one()
        return self._snooze_and_reload(15)

    def action_snooze_30(self):
        self.ensure_one()
        return self._snooze_and_reload(30)

    @api.model
    def get_pending_post_call_actions(self, limit=5):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            return []
        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 5
        now = fields.Datetime.now()
        records = self.search(
            [
                ("agent_id", "=", self.env.user.id),
                ("state", "=", "pending"),
                ("popup_completed_at", "=", False),
                "|",
                ("snoozed_until", "=", False),
                ("snoozed_until", "<=", now),
            ],
            order="ended_at asc, id asc",
            limit=limit,
        )
        return [
            {
                "followup_id": record.id,
                "event_id": record.event_id,
                "title": _("Complete post-call follow-up"),
                "message": record.name,
                "snooze_count": record.snooze_count,
            }
            for record in records
        ]

    @api.model
    def get_post_call_popup_state(self, followup_id):
        try:
            followup_id = int(followup_id)
        except (TypeError, ValueError):
            return {"found": False, "pending": False}
        record = self.search([("id", "=", followup_id)], limit=1)
        if not record:
            return {"found": False, "pending": False}
        now = fields.Datetime.now()
        is_pending = record.state == "pending" and not record.popup_completed_at
        is_due = is_pending and (
            not record.snoozed_until or record.snoozed_until <= now
        )
        return {
            "found": True,
            "followup_id": record.id,
            "state": record.state,
            "pending": is_pending,
            "due": is_due,
            "snoozed_until": (
                fields.Datetime.to_string(record.snoozed_until)
                if record.snoozed_until
                else False
            ),
        }

    @api.model
    def _cron_release_snoozed_followups(self, batch_size=500):
        try:
            batch_size = max(1, min(int(batch_size), 2000))
        except (TypeError, ValueError):
            batch_size = 500
        now = fields.Datetime.now()
        records = self.sudo().search(
            [
                ("state", "=", "pending"),
                ("popup_completed_at", "=", False),
                ("snoozed_until", "!=", False),
                ("snoozed_until", "<=", now),
            ],
            order="snoozed_until asc, id asc",
            limit=batch_size,
        )
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
