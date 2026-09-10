from odoo import fields, models


class CodestraCrmPostCallWizard(models.TransientModel):
    _inherit = "codestra.crm.post.call.wizard"

    popup_lease_owner = fields.Char(readonly=True)
    popup_lease_token = fields.Char(readonly=True)

    def _claim_pending_followup(self):
        """Validate popup ownership under the same lock that fences side effects."""
        self.ensure_one()
        followup = self.followup_id.exists()
        if not followup:
            return False
        self.env.cr.execute(
            f"SELECT id FROM {followup._table} WHERE id = %s AND state = 'pending' FOR UPDATE",
            [followup.id],
        )
        if not self.env.cr.fetchone():
            return False
        followup.invalidate_recordset()
        if self.popup_lease_owner or self.popup_lease_token:
            followup._validate_popup_lease(self.popup_lease_owner, self.popup_lease_token)
        return True
