from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


DELIVERY_INTENT_TYPES = [
    ("post_call_email", "Immediate Post-call Email"),
    ("callback_reminder", "Callback / Appointment Reminder"),
]

DELIVERY_AUDIENCES = [
    ("client", "Client"),
    ("agent", "Assigned Agent"),
]


class CodestraCrmCallDeliveryIntent(models.Model):
    """Durable Odoo-owned business intent consumed by Codestra Middleware.

    Odoo records *what* the business wants to send. Middleware remains the sole
    cross-system delivery boundary and owns consent/suppression, provider
    selection, retry, reconciliation, dead-letter handling, and final delivery.
    """

    _name = "codestra.crm.call.delivery.intent"
    _description = "CRM Call Delivery Intent"
    _order = "available_at asc, id asc"
    _rec_name = "name"

    name = fields.Char(required=True, readonly=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        index=True,
        ondelete="restrict",
    )
    followup_id = fields.Many2one(
        "codestra.crm.call.followup",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
        check_company=True,
    )
    intent_type = fields.Selection(
        DELIVERY_INTENT_TYPES,
        required=True,
        readonly=True,
        index=True,
    )
    audience = fields.Selection(
        DELIVERY_AUDIENCES,
        required=True,
        readonly=True,
        index=True,
    )
    channel = fields.Selection(
        [("email", "Email")],
        required=True,
        readonly=True,
        default="email",
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("claimed", "Claimed by Middleware"),
            ("delivered", "Delivered"),
            ("dead_letter", "Dead Letter"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        readonly=True,
        default="pending",
        index=True,
    )

    idempotency_key = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    correlation_id = fields.Char(readonly=True, copy=False, index=True)
    available_at = fields.Datetime(required=True, readonly=True, index=True)
    recipient_to = fields.Char(required=True, readonly=True)
    recipient_cc = fields.Char(readonly=True)
    subject = fields.Char(required=True, readonly=True)
    body_html = fields.Html(readonly=True, sanitize=True)
    requires_consent_check = fields.Boolean(
        required=True,
        readonly=True,
        default=True,
        help="Middleware must perform the authoritative consent and suppression check.",
    )

    lease_token = fields.Char(readonly=True, copy=False, index=True)
    lease_expires_at = fields.Datetime(readonly=True, copy=False, index=True)
    attempt_count = fields.Integer(readonly=True, default=0)
    provider_message_id = fields.Char(readonly=True, copy=False, index=True)
    last_error = fields.Text(readonly=True)
    delivered_at = fields.Datetime(readonly=True, copy=False)

    _intent_idempotency_unique = models.Constraint(
        "UNIQUE(company_id, idempotency_key)",
        "A delivery intent idempotency key can be used only once per company.",
    )

    @api.model
    def _require_service_user(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_service"
        ):
            raise AccessError(
                _("Only the authenticated Middleware service may claim delivery intents.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("codestra_delivery_workflow"):
            raise AccessError(
                _("Delivery intents can be created only by the call follow-up workflow.")
            )
        return super().create(vals_list)

    def write(self, values):
        if not self.env.context.get("codestra_delivery_workflow"):
            raise AccessError(
                _("Delivery intents can be changed only by the controlled delivery workflow.")
            )
        return super().write(values)

    def unlink(self):
        raise AccessError(
            _("Delivery intents are durable audit records and cannot be deleted.")
        )

    def _workflow_write(self, values):
        return self.with_context(codestra_delivery_workflow=True).write(values)

    @api.model
    def _service_visible_intent(self, intent_id):
        try:
            intent_id = int(intent_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("intent_id must be an integer.")) from exc
        intent = self.sudo().search(
            [
                ("id", "=", intent_id),
                ("company_id", "in", self.env.user.company_ids.ids),
            ],
            limit=1,
        )
        if not intent:
            raise AccessError(_("The delivery intent is not available to this service."))
        return intent

    @api.model
    def _lock_service_intent(self, intent_id):
        intent = self._service_visible_intent(intent_id)
        self.env.cr.execute(
            f"SELECT state, lease_token, lease_expires_at "
            f"FROM {intent._table} WHERE id = %s FOR UPDATE",
            [intent.id],
        )
        row = self.env.cr.fetchone()
        if not row:
            raise ValidationError(_("The delivery intent no longer exists."))
        intent.invalidate_recordset()
        return intent, row

    @api.model
    def claim_due_delivery_intents(self, limit=50, lease_seconds=120):
        """Lease due commands to Middleware with SKIP LOCKED concurrency safety."""

        self._require_service_user()
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 50
        try:
            lease_seconds = max(30, min(int(lease_seconds), 900))
        except (TypeError, ValueError):
            lease_seconds = 120

        company_ids = self.env.user.company_ids.ids
        if not company_ids:
            return []

        now = fields.Datetime.now()
        self.env.cr.execute(
            f"""
                SELECT id
                  FROM {self._table}
                 WHERE company_id = ANY(%s)
                   AND available_at <= %s
                   AND (
                        state = 'pending'
                        OR (
                            state = 'claimed'
                            AND lease_expires_at IS NOT NULL
                            AND lease_expires_at <= %s
                        )
                   )
                 ORDER BY available_at ASC, id ASC
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
            """,
            [company_ids, now, now, limit],
        )
        intent_ids = [row[0] for row in self.env.cr.fetchall()]
        if not intent_ids:
            return []

        intents = self.sudo().browse(intent_ids).exists()
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        response = []
        for intent in intents:
            lease_token = uuid4().hex
            intent._workflow_write(
                {
                    "state": "claimed",
                    "lease_token": lease_token,
                    "lease_expires_at": lease_expires_at,
                    "attempt_count": intent.attempt_count + 1,
                    "last_error": False,
                }
            )
            response.append(
                {
                    "intent_id": intent.id,
                    "company_id": intent.company_id.id,
                    "followup_id": intent.followup_id.id,
                    "intent_type": intent.intent_type,
                    "audience": intent.audience,
                    "channel": intent.channel,
                    "idempotency_key": intent.idempotency_key,
                    "correlation_id": intent.correlation_id or False,
                    "available_at": fields.Datetime.to_string(intent.available_at),
                    "recipient_to": intent.recipient_to,
                    "recipient_cc": intent.recipient_cc or False,
                    "subject": intent.subject,
                    "body_html": intent.body_html or "",
                    "requires_consent_check": intent.requires_consent_check,
                    "lease_token": lease_token,
                    "lease_expires_at": fields.Datetime.to_string(lease_expires_at),
                    "attempt_count": intent.attempt_count,
                }
            )
        return response

    @api.model
    def acknowledge_delivery_intent(
        self,
        intent_id,
        lease_token,
        provider_message_id=False,
        delivered_at=False,
    ):
        """Record a provider-confirmed delivery result from Middleware."""

        self._require_service_user()
        intent, row = self._lock_service_intent(intent_id)
        state, stored_token, lease_expires_at = row

        if state == "delivered":
            return {
                "intent_id": intent.id,
                "state": "delivered",
                "replayed": True,
                "provider_message_id": intent.provider_message_id or False,
            }
        if state != "claimed" or not lease_token or lease_token != stored_token:
            raise ValidationError(_("The delivery-intent lease is invalid."))
        if lease_expires_at and lease_expires_at < fields.Datetime.now():
            raise ValidationError(_("The delivery-intent lease has expired."))

        delivered_at = (
            self.env["codestra.crm.call.followup"]._parse_datetime(
                delivered_at,
                _("Delivery time"),
                required=False,
            )
            or fields.Datetime.now()
        )
        intent._workflow_write(
            {
                "state": "delivered",
                "provider_message_id": str(provider_message_id or "").strip() or False,
                "delivered_at": delivered_at,
                "lease_token": False,
                "lease_expires_at": False,
                "last_error": False,
            }
        )
        return {
            "intent_id": intent.id,
            "state": "delivered",
            "replayed": False,
            "provider_message_id": intent.provider_message_id or False,
        }

    @api.model
    def release_or_dead_letter_delivery_intent(
        self,
        intent_id,
        lease_token,
        error,
        retry_at=False,
        dead_letter=False,
    ):
        """Return a failed lease to the queue or move it to a durable dead letter."""

        self._require_service_user()
        intent, row = self._lock_service_intent(intent_id)
        state, stored_token, lease_expires_at = row
        if state != "claimed" or not lease_token or lease_token != stored_token:
            raise ValidationError(_("The delivery-intent lease is invalid."))
        if lease_expires_at and lease_expires_at < fields.Datetime.now():
            raise ValidationError(_("The delivery-intent lease has expired."))

        error = str(error or "").strip()
        if not error:
            raise ValidationError(_("A safe delivery failure reason is required."))
        if len(error) > 2000:
            error = error[:2000]

        values = {
            "state": "dead_letter" if dead_letter else "pending",
            "available_at": (
                self.env["codestra.crm.call.followup"]._parse_datetime(
                    retry_at,
                    _("Retry time"),
                    required=False,
                )
                or fields.Datetime.now()
            ),
            "lease_token": False,
            "lease_expires_at": False,
            "last_error": error,
        }
        intent._workflow_write(values)
        return {
            "intent_id": intent.id,
            "state": intent.state,
            "available_at": fields.Datetime.to_string(intent.available_at),
        }


class CodestraCrmCallFollowupDelivery(models.Model):
    _inherit = "codestra.crm.call.followup"

    delivery_intent_ids = fields.One2many(
        "codestra.crm.call.delivery.intent",
        "followup_id",
        string="Middleware Delivery Intents",
        readonly=True,
    )
    immediate_delivery_intent_id = fields.Many2one(
        "codestra.crm.call.delivery.intent",
        string="Immediate Email Intent",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    delivery_intent_count = fields.Integer(
        compute="_compute_delivery_intent_count",
        string="Delivery Intents",
    )

    def _compute_delivery_intent_count(self):
        for record in self:
            record.delivery_intent_count = self.env[
                "codestra.crm.call.delivery.intent"
            ].sudo().search_count([("followup_id", "=", record.id)])

    def action_open_delivery_intents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Middleware Delivery Intents"),
            "res_model": "codestra.crm.call.delivery.intent",
            "view_mode": "list,form",
            "domain": [("followup_id", "=", self.id)],
            "context": {"create": False},
            "target": "current",
        }

    def _delivery_workflow_model(self):
        return self.env["codestra.crm.call.delivery.intent"].sudo().with_context(
            codestra_delivery_workflow=True
        )

    def _render_delivery_template(self, xmlid):
        self.ensure_one()
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if not template:
            raise ValidationError(_("The required delivery template is not installed."))
        rendered = template.sudo()._generate_template(
            [self.id],
            ["subject", "body_html"],
        )
        return rendered.get(self.id, {})

    def _create_delivery_intent(
        self,
        *,
        intent_type,
        audience,
        idempotency_key,
        available_at,
        recipient_to,
        recipient_cc=False,
        subject,
        body_html,
    ):
        self.ensure_one()
        recipient_to = str(recipient_to or "").strip()
        if not recipient_to:
            raise ValidationError(_("A delivery-intent recipient is required."))

        model = self._delivery_workflow_model()
        existing = model.search(
            [
                ("company_id", "=", self.company_id.id),
                ("idempotency_key", "=", idempotency_key),
            ],
            limit=1,
        )
        if existing:
            if existing.state in {"cancelled", "dead_letter"}:
                existing._workflow_write(
                    {
                        "state": "pending",
                        "available_at": available_at,
                        "recipient_to": recipient_to,
                        "recipient_cc": str(recipient_cc or "").strip() or False,
                        "subject": str(subject or "").strip(),
                        "body_html": body_html or "",
                        "lease_token": False,
                        "lease_expires_at": False,
                        "last_error": False,
                    }
                )
            return existing

        return model.create(
            {
                "name": _("%s — %s") % (
                    dict(DELIVERY_INTENT_TYPES).get(intent_type, intent_type),
                    self.display_name,
                ),
                "company_id": self.company_id.id,
                "followup_id": self.id,
                "intent_type": intent_type,
                "audience": audience,
                "channel": "email",
                "state": "pending",
                "idempotency_key": idempotency_key,
                "correlation_id": self.correlation_id or False,
                "available_at": available_at,
                "recipient_to": recipient_to,
                "recipient_cc": str(recipient_cc or "").strip() or False,
                "subject": str(subject or "").strip(),
                "body_html": body_html or "",
                "requires_consent_check": True,
            }
        )

    def _cancel_open_reminder_delivery_intents(self):
        for followup in self:
            active = followup.sudo().delivery_intent_ids.filtered(
                lambda intent: (
                    intent.intent_type == "callback_reminder"
                    and intent.state in {"pending", "claimed"}
                )
            )
            if active:
                active._workflow_write(
                    {
                        "state": "cancelled",
                        "lease_token": False,
                        "lease_expires_at": False,
                    }
                )

    def _sync_reminder_delivery_intents(self):
        """Replace undelivered reminder intents after schedule changes."""

        for followup in self:
            followup._cancel_open_reminder_delivery_intents()
            if (
                not followup.reminder_email_enabled
                or followup.schedule_kind not in {"callback", "appointment"}
                or not followup.callback_at
            ):
                continue

            available_at = max(
                fields.Datetime.now(),
                followup.callback_at - timedelta(minutes=15),
            )
            schedule_token = fields.Datetime.to_string(followup.callback_at).replace(
                " ", "T"
            )
            client_email = (
                followup.partner_id.email
                or followup.lead_id.email_from
                or ""
            ).strip()
            agent_email = (followup.agent_id.email or "").strip()

            if client_email:
                rendered = followup._render_delivery_template(
                    "codestra_crm_call_followup."
                    "mail_template_callback_reminder_client_15"
                )
                followup._create_delivery_intent(
                    intent_type="callback_reminder",
                    audience="client",
                    idempotency_key=(
                        f"call-followup:{followup.company_id.id}:{followup.id}:"
                        f"reminder:client:{schedule_token}:v1"
                    ),
                    available_at=available_at,
                    recipient_to=client_email,
                    subject=rendered.get("subject"),
                    body_html=rendered.get("body_html"),
                )

            if agent_email:
                rendered = followup._render_delivery_template(
                    "codestra_crm_call_followup."
                    "mail_template_callback_reminder_agent_15"
                )
                followup._create_delivery_intent(
                    intent_type="callback_reminder",
                    audience="agent",
                    idempotency_key=(
                        f"call-followup:{followup.company_id.id}:{followup.id}:"
                        f"reminder:agent:{schedule_token}:v1"
                    ),
                    available_at=available_at,
                    recipient_to=agent_email,
                    subject=rendered.get("subject"),
                    body_html=rendered.get("body_html"),
                )
