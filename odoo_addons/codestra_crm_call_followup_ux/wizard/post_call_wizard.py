from odoo import _, fields, models
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

    def action_snooze_5(self):
        self.ensure_one()
        return self.followup_id.action_snooze_5()

    def action_snooze_15(self):
        self.ensure_one()
        return self.followup_id.action_snooze_15()

    def action_snooze_30(self):
        self.ensure_one()
        return self.followup_id.action_snooze_30()

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
            raise ValidationError(_("This call is not linked to a CRM lead or opportunity."))
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
            raise ValidationError(_("This call is not linked to a customer."))
        return {
            "type": "ir.actions.act_window",
            "name": self.partner_id.display_name,
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }
