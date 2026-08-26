from odoo import _, api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    codestra_call_followup_ids = fields.One2many(
        "codestra.crm.call.followup",
        "lead_id",
        string="Call Follow-ups",
    )
    codestra_call_followup_count = fields.Integer(
        string="Call Follow-up Count",
        compute="_compute_codestra_call_followup_count",
    )
    codestra_next_callback_at = fields.Datetime(
        string="Next Callback",
        compute="_compute_codestra_next_callback_at",
    )

    @api.depends("codestra_call_followup_ids")
    def _compute_codestra_call_followup_count(self):
        for lead in self:
            lead.codestra_call_followup_count = len(lead.codestra_call_followup_ids)

    @api.depends(
        "codestra_call_followup_ids.state",
        "codestra_call_followup_ids.callback_at",
        "codestra_call_followup_ids.schedule_kind",
    )
    def _compute_codestra_next_callback_at(self):
        now = fields.Datetime.now()
        for lead in self:
            upcoming = lead.codestra_call_followup_ids.filtered(
                lambda item: item.state == "completed"
                and item.schedule_kind != "none"
                and item.callback_at
                and item.callback_at >= now
            ).sorted("callback_at")
            lead.codestra_next_callback_at = upcoming[:1].callback_at or False

    def action_view_codestra_call_followups(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "codestra_crm_call_followup.action_codestra_call_followup"
        )
        action.update(
            {
                "name": _("Call Follow-ups — %s") % self.display_name,
                "domain": [("lead_id", "=", self.id)],
                "context": {
                    "default_lead_id": self.id,
                    "default_partner_id": self.partner_id.id,
                    "search_default_my_followups": 1,
                },
            }
        )
        return action
