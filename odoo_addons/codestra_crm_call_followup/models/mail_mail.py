from odoo import fields, models


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _record_codestra_sent(self, confirmed=False):
        sent = self if confirmed else self.filtered(lambda mail: mail.state == "sent")
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

    def _postprocess_sent_message(
        self, success_pids, success_emails, failure_reason=False, failure_type=None
    ):
        # Odoo may auto-delete the row from this hook. Persist the durable
        # business outcome before delegating, using the SMTP success sets rather
        # than the transient mail state as the authority.
        if success_pids or success_emails:
            self._record_codestra_sent(confirmed=True)
        return super()._postprocess_sent_message(
            success_pids,
            success_emails,
            failure_reason=failure_reason,
            failure_type=failure_type,
        )

    def unlink(self):
        # Auto-deleting templates unlink successful mail rows immediately after
        # transmission, so preserve the delivery outcome first.
        self._record_codestra_sent()
        return super().unlink()
