from odoo import fields, models


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _record_codestra_sent(self):
        sent = self.filtered(lambda mail: mail.state == "sent")
        if not sent:
            return
        followups = self.env["codestra.crm.call.followup"].sudo().search([
            ("mail_id", "in", sent.ids),
            ("email_sent_at", "=", False),
        ])
        if followups:
            followups._write_from_workflow({"email_sent_at": fields.Datetime.now()})

    def write(self, values):
        result = super().write(values)
        if values.get("state") == "sent":
            self._record_codestra_sent()
        return result

    def unlink(self):
        # Auto-deleting templates unlink successful mail rows immediately after
        # transmission, so preserve the delivery outcome first.
        self._record_codestra_sent()
        return super().unlink()
