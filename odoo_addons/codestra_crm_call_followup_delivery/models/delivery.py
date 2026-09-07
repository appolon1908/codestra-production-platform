from __future__ import annotations

import hashlib
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


BACKOFF_MINUTES = (1, 5, 15, 60, 360)
MAX_ERROR_LENGTH = 1000


class CodestraCrmCallDelivery(models.Model):
    _name = "codestra.crm.call.delivery"
    _description = "CRM Call Follow-up Delivery"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True, copy=False)
    kind = fields.Selection(
        [("post_call_email", "Immediate Post-call Email")],
        required=True,
        readonly=True,
        default="post_call_email",
        index=True,
    )
    state = fields.Selection(
        [
            ("queued", "Queued"),
            ("sent", "Sent"),
            ("failed", "Retry Scheduled"),
            ("dead", "Dead Letter"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="queued",
        readonly=True,
        tracking=True,
        index=True,
    )

    followup_id = fields.Many2one(
        "codestra.crm.call.followup",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    company_id = fields.Many2one(
        related="followup_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    agent_id = fields.Many2one(
        related="followup_id.agent_id",
        store=True,
        readonly=True,
        index=True,
    )
    lead_id = fields.Many2one(
        related="followup_id.lead_id",
        store=True,
        readonly=True,
        index=True,
    )
    partner_id = fields.Many2one(
        related="followup_id.partner_id",
        store=True,
        readonly=True,
        index=True,
    )

    recipient_hash = fields.Char(required=True, readonly=True, index=True, copy=False)
    email_to = fields.Char(required=True, readonly=True)
    email_cc = fields.Char(readonly=True)
    subject = fields.Char(required=True, readonly=True)
    body_html = fields.Html(readonly=True, sanitize=True)
    mail_id = fields.Many2one(
        "mail.mail",
        readonly=True,
        index=True,
        copy=False,
        ondelete="set null",
    )

    attempt_count = fields.Integer(default=0, required=True, readonly=True, tracking=True)
    max_attempts = fields.Integer(default=5, required=True, readonly=True)
    next_attempt_at = fields.Datetime(readonly=True, index=True, copy=False)
    last_attempt_at = fields.Datetime(readonly=True, copy=False)
    queued_at = fields.Datetime(
        default=fields.Datetime.now,
        required=True,
        readonly=True,
        copy=False,
    )
    sent_at = fields.Datetime(readonly=True, copy=False)
    last_error = fields.Text(readonly=True, copy=False)

    _idempotency_unique = models.Constraint(
        "UNIQUE(idempotency_key)",
        "A call follow-up delivery idempotency key can be used only once.",
    )
    _attempt_count_non_negative = models.Constraint(
        "CHECK(attempt_count >= 0)",
        "Delivery attempt count cannot be negative.",
    )
    _max_attempts_positive = models.Constraint(
        "CHECK(max_attempts > 0)",
        "Maximum delivery attempts must be greater than zero.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.context.get("codestra_delivery_enqueue"):
            raise AccessError(_("Deliveries may be created only by the outbox workflow."))
        return super().create(values_list)

    def write(self, values):
        if not self.env.context.get("codestra_delivery_worker"):
            raise AccessError(_("Delivery state may be changed only by the outbox workflow."))
        return super().write(values)

    @api.ondelete(at_uninstall=False)
    def _prevent_delivery_deletion(self):
        raise AccessError(_("Delivery audit records cannot be deleted."))

    def _write_from_worker(self, values):
        return self.with_context(codestra_delivery_worker=True).write(values)

    @api.model
    def _recipient_hash(self, email_to):
        return hashlib.sha256((email_to or "").strip().lower().encode()).hexdigest()

    @api.model
    def _idempotency_key(self, followup, kind, recipient_hash):
        material = (
            f"{followup.company_id.id}:{followup.id}:{kind}:"
            f"{recipient_hash}:v1"
        )
        return hashlib.sha256(material.encode()).hexdigest()

    @api.model
    def enqueue_post_call_email(
        self,
        followup,
        mail,
        *,
        email_to,
        email_cc=False,
        subject,
        body_html,
    ):
        followup.ensure_one()
        mail.ensure_one()
        recipient_hash = self._recipient_hash(email_to)
        key = self._idempotency_key(
            followup,
            "post_call_email",
            recipient_hash,
        )
        Delivery = self.sudo()
        existing = Delivery.search([("idempotency_key", "=", key)], limit=1)
        if existing:
            if existing.followup_id != followup or existing.recipient_hash != recipient_hash:
                raise ValidationError(_("DELIVERY_IDEMPOTENCY_CONFLICT"))
            return existing

        # Preserve the mail row so delivery reconciliation can prove the final state.
        mail.sudo().write({"auto_delete": False})
        values = {
            "name": _("Post-call email — %s") % followup.display_name,
            "idempotency_key": key,
            "kind": "post_call_email",
            "followup_id": followup.id,
            "recipient_hash": recipient_hash,
            "email_to": email_to,
            "email_cc": email_cc or False,
            "subject": subject,
            "body_html": body_html,
            "mail_id": mail.id,
            "state": "queued",
            "queued_at": fields.Datetime.now(),
        }
        try:
            with self.env.cr.savepoint():
                return Delivery.with_context(codestra_delivery_enqueue=True).create(values)
        except IntegrityError:
            existing = Delivery.search([("idempotency_key", "=", key)], limit=1)
            if not existing:
                raise
            return existing

    def _mail_values(self):
        self.ensure_one()
        sender = (
            self.agent_id.email_formatted
            or self.company_id.email_formatted
            or self.env.user.email_formatted
        )
        values = {
            "email_to": self.email_to,
            "email_cc": self.email_cc or False,
            "author_id": self.agent_id.partner_id.id,
            "subject": self.subject,
            "body_html": self.body_html,
            "auto_delete": False,
        }
        if sender:
            values["email_from"] = sender
        return values

    def _create_replacement_mail(self):
        self.ensure_one()
        template = self.env.ref(
            "codestra_crm_call_followup.mail_template_post_call_followup"
        ).sudo()
        mail_id = template.send_mail(
            self.followup_id.id,
            force_send=False,
            raise_exception=True,
            email_values=self._mail_values(),
        )
        mail = self.env["mail.mail"].sudo().browse(mail_id)
        mail.write({"auto_delete": False})
        return mail

    def _record_failure(self, error):
        self.ensure_one()
        attempts = self.attempt_count + 1
        dead = attempts >= self.max_attempts
        delay = BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)]
        self._write_from_worker(
            {
                "state": "dead" if dead else "failed",
                "attempt_count": attempts,
                "last_attempt_at": fields.Datetime.now(),
                "next_attempt_at": (
                    False
                    if dead
                    else fields.Datetime.now() + timedelta(minutes=delay)
                ),
                "last_error": str(error or _("Unknown mail failure"))[:MAX_ERROR_LENGTH],
            }
        )

    def _mark_sent(self):
        self.ensure_one()
        self._write_from_worker(
            {
                "state": "sent",
                "sent_at": fields.Datetime.now(),
                "next_attempt_at": False,
                "last_error": False,
            }
        )

    def _queue_retry(self, *, manual=False):
        self.ensure_one()
        # Serialize the decision and replacement creation. Without this lock,
        # concurrent manager retries can each create a sendable orphan mail.
        self.flush_recordset(["state", "mail_id", "attempt_count", "max_attempts"])
        self.env.cr.execute(
            "SELECT id FROM codestra_crm_call_delivery WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(["state", "mail_id", "attempt_count", "max_attempts"])
        if self.state == "sent":
            raise ValidationError(_("A sent delivery cannot be retried."))
        if self.state == "cancelled":
            raise ValidationError(_("A cancelled delivery must be reopened by an administrator."))
        if self.attempt_count >= self.max_attempts and not manual:
            raise ValidationError(_("The delivery has exhausted its retry budget."))

        mail = self.mail_id.sudo()
        if mail and mail.state == "sent":
            self._mark_sent()
            return
        if mail and mail.state == "cancel":
            self._write_from_worker({"state": "cancelled", "next_attempt_at": False})
            return
        if not mail:
            mail = self._create_replacement_mail()
        else:
            mail.write({"state": "outgoing", "failure_reason": False})
        values = {
            "state": "queued",
            "mail_id": mail.id,
            "next_attempt_at": False,
            "last_error": False,
            "last_attempt_at": fields.Datetime.now(),
        }
        if manual and self.attempt_count >= self.max_attempts:
            values["max_attempts"] = self.attempt_count + 1
        self._write_from_worker(
            values
        )

    @api.model
    def _cron_reconcile_mail_states(self, limit=200):
        # Select only rows that can make progress. A large stable outgoing
        # backlog must not starve later terminal mail outcomes.
        self.flush_model(["state", "mail_id"])
        self.env["mail.mail"].flush_model(["state"])
        self.env.cr.execute(
            """
            SELECT d.id
              FROM codestra_crm_call_delivery d
         LEFT JOIN mail_mail m ON m.id = d.mail_id
             WHERE (d.state = 'queued'
                    AND (m.id IS NULL OR m.state IN ('sent', 'exception', 'cancel')))
                OR (d.state = 'failed' AND m.state IN ('sent', 'cancel'))
             ORDER BY d.id
             LIMIT %s
             FOR UPDATE OF d SKIP LOCKED
            """,
            [max(1, min(int(limit), 1000))],
        )
        records = self.sudo().browse([row[0] for row in self.env.cr.fetchall()])
        for delivery in records:
            mail = delivery.mail_id.sudo()
            if not mail:
                delivery._record_failure(_("Queued mail record is missing."))
            elif mail.state == "sent":
                delivery._mark_sent()
            elif mail.state == "cancel":
                delivery._write_from_worker(
                    {"state": "cancelled", "next_attempt_at": False}
                )
            elif mail.state == "exception":
                delivery._record_failure(
                    mail.failure_reason or _("Odoo mail queue reported %s") % mail.state
                )
        return True

    @api.model
    def _cron_retry_failed(self, limit=50):
        now = fields.Datetime.now()
        self.flush_model(["state", "attempt_count", "max_attempts", "next_attempt_at"])
        self.env.cr.execute(
            """
            SELECT id
              FROM codestra_crm_call_delivery
             WHERE state = 'failed'
               AND attempt_count < max_attempts
               AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
             ORDER BY next_attempt_at NULLS FIRST, id
             LIMIT %s
             FOR UPDATE SKIP LOCKED
            """,
            [now, max(1, min(int(limit), 200))],
        )
        records = self.sudo().browse([row[0] for row in self.env.cr.fetchall()])
        for delivery in records:
            try:
                with self.env.cr.savepoint():
                    delivery._queue_retry()
            except Exception as exc:  # cron isolates each delivery
                delivery._record_failure(exc)
        return True

    def _require_manager(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_manager"
        ):
            raise AccessError(_("Call Follow-up manager access is required."))

    def action_retry_now(self):
        self._require_manager()
        for delivery in self:
            delivery.check_access("read")
            delivery.sudo()._queue_retry(manual=True)
        return True

    def action_cancel(self):
        self._require_manager()
        for delivery in self:
            delivery.check_access("read")
            if delivery.mail_id.sudo().state == "sent":
                delivery.sudo()._mark_sent()
                continue
            if delivery.state == "sent":
                raise ValidationError(_("A sent delivery cannot be cancelled."))
            if delivery.mail_id:
                mail = delivery.mail_id.sudo()
                if mail.state != "cancel":
                    mail.write({"state": "cancel"})
                mail.invalidate_recordset(["state"])
                if mail.state != "cancel":
                    raise ValidationError(_("The linked Odoo mail could not be cancelled."))
            delivery.sudo()._write_from_worker(
                {
                    "state": "cancelled",
                    "next_attempt_at": False,
                }
            )
        return True

    def action_open_followup(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.followup_id.display_name,
            "res_model": "codestra.crm.call.followup",
            "res_id": self.followup_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_open_mail(self):
        self.ensure_one()
        if not self.mail_id:
            raise ValidationError(_("No Odoo mail record is linked."))
        return {
            "type": "ir.actions.act_window",
            "name": self.mail_id.display_name,
            "res_model": "mail.mail",
            "res_id": self.mail_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }
