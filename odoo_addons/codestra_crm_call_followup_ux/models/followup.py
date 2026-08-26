from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CodestraCrmCallFollowupWorkspace(models.Model):
    _inherit = "codestra.crm.call.followup"

    ux_contact_label = fields.Char(compute="_compute_ux_labels")
    ux_call_duration_label = fields.Char(compute="_compute_ux_labels")
    ux_next_step_summary = fields.Char(compute="_compute_ux_labels")
    ux_has_customer = fields.Boolean(compute="_compute_ux_flags")
    ux_has_opportunity = fields.Boolean(compute="_compute_ux_flags")
    ux_has_calendar_event = fields.Boolean(compute="_compute_ux_flags")
    ux_can_complete = fields.Boolean(compute="_compute_ux_flags")

    @api.depends(
        "partner_id",
        "lead_id",
        "duration_seconds",
        "schedule_kind",
        "callback_at",
        "calendar_event_id",
    )
    def _compute_ux_labels(self):
        for record in self:
            lead_partner = record.lead_id.partner_id
            record.ux_contact_label = (
                record.partner_id.display_name
                or lead_partner.display_name
                or record.lead_id.contact_name
                or record.lead_id.display_name
                or _("Unmatched caller")
            )
            seconds = max(0, record.duration_seconds or 0)
            minutes, remainder = divmod(seconds, 60)
            record.ux_call_duration_label = _("%s min %s sec") % (
                minutes,
                remainder,
            )
            if record.schedule_kind == "none" or not record.callback_at:
                record.ux_next_step_summary = _(
                    "No callback or appointment scheduled"
                )
            else:
                local_time = fields.Datetime.context_timestamp(
                    record,
                    record.callback_at,
                )
                label = (
                    _("Callback")
                    if record.schedule_kind == "callback"
                    else _("Appointment")
                )
                record.ux_next_step_summary = _("%s · %s") % (
                    label,
                    local_time.strftime("%b %d, %Y %I:%M %p %Z"),
                )

    @api.depends(
        "partner_id",
        "lead_id",
        "calendar_event_id",
        "state",
        "agent_id",
    )
    def _compute_ux_flags(self):
        for record in self:
            record.ux_has_customer = bool(
                record.partner_id or record.lead_id.partner_id
            )
            record.ux_has_opportunity = bool(record.lead_id)
            record.ux_has_calendar_event = bool(record.calendar_event_id)
            record.ux_can_complete = bool(
                record.state == "pending"
                and record.agent_id == self.env.user
            )

    def action_ux_open_self(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": self._name,
            "res_id": self.id,
            "views": [(False, "form")],
            "target": "current",
        }

    def action_ux_open_customer(self):
        self.ensure_one()
        partner = self.partner_id or self.lead_id.partner_id
        if not partner:
            raise UserError(_("No customer record is linked to this call."))
        return {
            "type": "ir.actions.act_window",
            "name": partner.display_name,
            "res_model": "res.partner",
            "res_id": partner.id,
            "views": [(False, "form")],
            "target": "current",
        }

    def action_ux_open_opportunity(self):
        self.ensure_one()
        if not self.lead_id:
            raise UserError(
                _("No CRM lead or opportunity is linked to this call.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.lead_id.display_name,
            "res_model": "crm.lead",
            "res_id": self.lead_id.id,
            "views": [(False, "form")],
            "target": "current",
        }

    def action_ux_open_calendar(self):
        self.ensure_one()
        if not self.calendar_event_id:
            raise UserError(_("No calendar event is linked to this call."))
        return {
            "type": "ir.actions.act_window",
            "name": self.calendar_event_id.display_name,
            "res_model": "calendar.event",
            "res_id": self.calendar_event_id.id,
            "views": [(False, "form")],
            "target": "current",
        }

    def action_ux_primary(self):
        self.ensure_one()
        if self.ux_can_complete:
            return self.action_open_post_call_wizard()
        if self.calendar_event_id:
            return self.action_ux_open_calendar()
        if self.lead_id:
            return self.action_ux_open_opportunity()
        if self.partner_id:
            return self.action_ux_open_customer()
        return self.action_ux_open_self()
