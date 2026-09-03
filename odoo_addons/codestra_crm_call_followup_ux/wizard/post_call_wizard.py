from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CodestraCrmPostCallWizardUx(models.TransientModel):
    _inherit = "codestra.crm.post.call.wizard"

    snoozed_until = fields.Datetime(
        related="followup_id.snoozed_until",
        readonly=True,
    )
    snooze_count = fields.Integer(
        related="followup_id.snooze_count",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for raw_values in vals_list:
            values = dict(raw_values)
            if not values.get("disposition"):
                followup = self.env[
                    "codestra.crm.call.followup"
                ].browse(values.get("followup_id")).exists()
                values["disposition"] = (
                    followup.disposition if followup else False
                ) or "contacted"
            prepared.append(values)
        return super().create(prepared)

    def _snooze_and_close(self, minutes):
        self.ensure_one()
        self.followup_id._snooze_for(minutes)
        return {"type": "ir.actions.act_window_close"}

    def action_snooze_5(self):
        self.ensure_one()
        return self._snooze_and_close(5)

    def action_snooze_15(self):
        self.ensure_one()
        return self._snooze_and_close(15)

    def action_snooze_30(self):
        self.ensure_one()
        return self._snooze_and_close(30)

    def action_send_email_and_complete(self):
        self.ensure_one()
        self.send_post_call_email = True
        return self.action_complete()

    def action_schedule_and_complete(self):
        self.ensure_one()
        if self.schedule_kind == "none":
            raise ValidationError(_("Select Callback or Appointment first."))
        return self.action_complete_without_email()

    def action_open_crm_record(self):
        self.ensure_one()
        if not self.lead_id:
            raise ValidationError(
                _("This call is not linked to a CRM lead or opportunity.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.lead_id.display_name,
            "res_model": "crm.lead",
            "res_id": self.lead_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_open_customer(self):
        self.ensure_one()
        if not self.partner_id:
            raise ValidationError(
                _("This call is not linked to a customer.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": self.partner_id.display_name,
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }
