from odoo import models


class CodestraPostCallWizardDelivery(models.TransientModel):
    _inherit = "codestra.crm.post.call.wizard"

    def _queue_post_call_email(self):
        """Retain the native queued mail and bind it to an auditable ledger."""
        self.ensure_one()
        mail = super()._queue_post_call_email()
        if not mail:
            return mail
        self.env["codestra.crm.call.delivery"].enqueue_post_call_email(
            self.followup_id,
            mail,
            email_to=self.email_to.strip(),
            email_cc=(self.email_cc or "").strip() or False,
            subject=self.email_subject.strip(),
            body_html=self.email_body,
        )
        return mail
