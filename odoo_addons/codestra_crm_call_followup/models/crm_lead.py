from odoo import _, api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    codestra_call_followup_ids = fields.One2many(
        "codestra.crm.call.followup",
        "lead_id",
        string="Call History",
    )
    codestra_call_followup_count = fields.Integer(
        string="Call Follow-up Count",
        compute="_compute_codestra_call_metrics",
    )
    codestra_pending_call_followup_count = fields.Integer(
        string="Pending Call Actions",
        compute="_compute_codestra_call_metrics",
    )
    codestra_next_callback_at = fields.Datetime(
        string="Next Callback",
        compute="_compute_codestra_call_metrics",
    )
    codestra_last_call_at = fields.Datetime(
        string="Last Call",
        compute="_compute_codestra_call_metrics",
    )

    @api.depends(
        "codestra_call_followup_ids",
        "codestra_call_followup_ids.state",
        "codestra_call_followup_ids.callback_at",
        "codestra_call_followup_ids.schedule_kind",
        "codestra_call_followup_ids.ended_at",
    )
    def _compute_codestra_call_metrics(self):
        for lead in self:
            lead.codestra_call_followup_count = 0
            lead.codestra_pending_call_followup_count = 0
            lead.codestra_next_callback_at = False
            lead.codestra_last_call_at = False

        if not self.ids:
            return

        Followup = self.env["codestra.crm.call.followup"]
        totals = Followup.read_group(
            [("lead_id", "in", self.ids)],
            ["lead_id", "ended_at:max"],
            ["lead_id"],
            lazy=False,
        )
        for row in totals:
            lead_id = row.get("lead_id") and row["lead_id"][0]
            if not lead_id:
                continue
            lead = self.browse(lead_id)
            lead.codestra_call_followup_count = row.get(
                "lead_id_count", 0
            )
            lead.codestra_last_call_at = row.get("ended_at") or False

        pending = Followup.read_group(
            [
                ("lead_id", "in", self.ids),
                ("state", "=", "pending"),
            ],
            ["lead_id"],
            ["lead_id"],
            lazy=False,
        )
        for row in pending:
            lead_id = row.get("lead_id") and row["lead_id"][0]
            if lead_id:
                self.browse(
                    lead_id
                ).codestra_pending_call_followup_count = row.get(
                    "lead_id_count", 0
                )

        upcoming = Followup.read_group(
            [
                ("lead_id", "in", self.ids),
                ("state", "=", "completed"),
                ("schedule_kind", "!=", "none"),
                ("callback_at", ">=", fields.Datetime.now()),
            ],
            ["lead_id", "callback_at:min"],
            ["lead_id"],
            lazy=False,
        )
        for row in upcoming:
            lead_id = row.get("lead_id") and row["lead_id"][0]
            if lead_id:
                self.browse(lead_id).codestra_next_callback_at = (
                    row.get("callback_at") or False
                )

    def _codestra_call_followup_action(self, *, pending_only=False):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "codestra_crm_call_followup.action_codestra_call_followup"
        )
        domain = [("lead_id", "=", self.id)]
        if pending_only:
            domain.append(("state", "=", "pending"))
        action.update(
            {
                "name": (
                    _("Pending Call Actions — %s")
                    if pending_only
                    else _("Call Follow-ups — %s")
                )
                % self.display_name,
                "domain": domain,
                "context": {
                    "default_lead_id": self.id,
                    "default_partner_id": self.partner_id.id,
                    "search_default_my_followups": 1,
                    "search_default_pending": int(pending_only),
                },
            }
        )
        return action

    def action_view_codestra_call_followups(self):
        return self._codestra_call_followup_action(pending_only=False)

    def action_view_codestra_pending_call_followups(self):
        return self._codestra_call_followup_action(pending_only=True)
