from __future__ import annotations

from datetime import timedelta
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


REALTIME_CHANNEL = "codestra_crm_call_followup.post_call"


class CodestraCrmCallFollowupRealtime(models.Model):
    _inherit = "codestra.crm.call.followup"

    rt_claim_token = fields.Char(readonly=True, copy=False, index=True, groups="base.group_system")
    rt_claimed_by_id = fields.Many2one(
        "res.users",
        string="Popup claimed by",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )
    rt_claimed_client_id = fields.Char(
        string="Browser client",
        readonly=True,
        copy=False,
        index=True,
        groups="base.group_system",
    )
    rt_claimed_at = fields.Datetime(readonly=True, copy=False)
    rt_claim_expires_at = fields.Datetime(readonly=True, copy=False, index=True)
    rt_popup_opened_at = fields.Datetime(readonly=True, copy=False)
    rt_last_heartbeat_at = fields.Datetime(readonly=True, copy=False)
    rt_delivery_attempts = fields.Integer(readonly=True, copy=False, default=0)
    rt_last_delivery_at = fields.Datetime(readonly=True, copy=False)
    rt_supervisor_notified_at = fields.Datetime(readonly=True, copy=False)
    rt_claim_state = fields.Selection(
        [
            ("available", "Available"),
            ("claimed", "Claimed"),
            ("expired", "Expired"),
            ("closed", "Closed"),
        ],
        compute="_compute_rt_claim_state",
        string="Popup delivery",
    )
    rt_pending_overdue = fields.Boolean(
        compute="_compute_rt_pending_overdue",
        string="Pending SLA overdue",
    )

    @api.depends("state", "popup_completed_at", "rt_claim_token", "rt_claim_expires_at")
    def _compute_rt_claim_state(self):
        now = fields.Datetime.now()
        for record in self:
            if record.state != "pending" or record.popup_completed_at:
                record.rt_claim_state = "closed"
            elif not record.rt_claim_token:
                record.rt_claim_state = "available"
            elif record.rt_claim_expires_at and record.rt_claim_expires_at <= now:
                record.rt_claim_state = "expired"
            else:
                record.rt_claim_state = "claimed"

    @api.depends("state", "ended_at", "popup_completed_at")
    def _compute_rt_pending_overdue(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "codestra.crm.followup.realtime.pending_sla_minutes", "10"
        )
        try:
            sla_minutes = max(1, min(int(raw), 1440))
        except (TypeError, ValueError):
            sla_minutes = 10
        cutoff = fields.Datetime.now() - timedelta(minutes=sla_minutes)
        for record in self:
            record.rt_pending_overdue = bool(
                record.state == "pending"
                and not record.popup_completed_at
                and record.ended_at
                and record.ended_at <= cutoff
            )

    def _rt_assert_assigned_agent(self):
        self.ensure_one()
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            raise AccessError(_("Call follow-up agent access is required."))
        if self.agent_id != self.env.user:
            raise AccessError(_("Only the assigned agent may claim this post-call action."))
        self.check_access("read")

    @api.model
    def _rt_validate_client_id(self, client_id):
        client_id = str(client_id or "").strip()
        if not client_id or len(client_id) > 128:
            raise ValidationError(_("client_id must contain 1 to 128 characters."))
        return client_id

    @api.model
    def _rt_validate_lease_seconds(self, lease_seconds):
        try:
            lease_seconds = int(lease_seconds)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("lease_seconds must be an integer.")) from exc
        if not 30 <= lease_seconds <= 300:
            raise ValidationError(_("lease_seconds must be between 30 and 300."))
        return lease_seconds

    def _rt_lock(self):
        self.ensure_one()
        self.env.cr.execute(
            f"SELECT id FROM {self._table} WHERE id = %s FOR UPDATE",
            [self.id],
        )
        if not self.env.cr.fetchone():
            raise ValidationError(_("The post-call action no longer exists."))
        self.invalidate_recordset(
            [
                "state",
                "popup_completed_at",
                "rt_claim_token",
                "rt_claimed_by_id",
                "rt_claimed_client_id",
                "rt_claim_expires_at",
            ]
        )

    def _rt_claim_payload(self, status, token=False):
        self.ensure_one()
        return {
            "api_version": "1.0",
            "status": status,
            "followup_id": self.id,
            "event_id": self.event_id,
            "claim_token": token or False,
            "claim_expires_at": fields.Datetime.to_string(self.rt_claim_expires_at)
            if self.rt_claim_expires_at
            else False,
            "claimed_by_user_id": self.rt_claimed_by_id.id or False,
            "action": self.action_open_post_call_wizard() if status == "claimed" else False,
        }

    def rt_claim_v1(self, client_id, lease_seconds=90):
        self.ensure_one()
        self._rt_assert_assigned_agent()
        client_id = self._rt_validate_client_id(client_id)
        lease_seconds = self._rt_validate_lease_seconds(lease_seconds)
        self._rt_lock()

        if self.state != "pending" or self.popup_completed_at:
            return self._rt_claim_payload("closed")

        now = fields.Datetime.now()
        claim_active = bool(
            self.rt_claim_token
            and self.rt_claim_expires_at
            and self.rt_claim_expires_at > now
        )
        same_owner = bool(
            self.rt_claimed_by_id == self.env.user
            and self.rt_claimed_client_id == client_id
        )
        if claim_active and not same_owner:
            return self._rt_claim_payload("busy")

        token = uuid.uuid4().hex
        expires_at = now + timedelta(seconds=lease_seconds)
        self._write_from_workflow(
            {
                "rt_claim_token": token,
                "rt_claimed_by_id": self.env.user.id,
                "rt_claimed_client_id": client_id,
                "rt_claimed_at": now,
                "rt_claim_expires_at": expires_at,
                "rt_last_heartbeat_at": now,
                "rt_last_delivery_at": now,
                "rt_delivery_attempts": self.rt_delivery_attempts + 1,
            }
        )
        return self._rt_claim_payload("claimed", token=token)

    def rt_ack_opened_v1(self, claim_token):
        self.ensure_one()
        self._rt_assert_assigned_agent()
        self._rt_lock()
        if not claim_token or claim_token != self.rt_claim_token:
            raise AccessError(_("The popup claim token is invalid or expired."))
        now = fields.Datetime.now()
        self._write_from_workflow(
            {
                "rt_popup_opened_at": self.rt_popup_opened_at or now,
                "rt_last_heartbeat_at": now,
            }
        )
        return {"api_version": "1.0", "status": "opened", "followup_id": self.id}

    def rt_renew_v1(self, claim_token, lease_seconds=90):
        self.ensure_one()
        self._rt_assert_assigned_agent()
        lease_seconds = self._rt_validate_lease_seconds(lease_seconds)
        self._rt_lock()
        now = fields.Datetime.now()
        if (
            not claim_token
            or claim_token != self.rt_claim_token
            or self.rt_claimed_by_id != self.env.user
            or not self.rt_claim_expires_at
            or self.rt_claim_expires_at <= now
        ):
            return self._rt_claim_payload("expired")
        self._write_from_workflow(
            {
                "rt_claim_expires_at": now + timedelta(seconds=lease_seconds),
                "rt_last_heartbeat_at": now,
            }
        )
        return self._rt_claim_payload("renewed", token=claim_token)

    def rt_release_v1(self, claim_token, reason="closed"):
        self.ensure_one()
        self._rt_assert_assigned_agent()
        reason = str(reason or "closed").strip()
        if reason not in {"closed", "completed", "snoozed", "navigation", "error"}:
            raise ValidationError(_("Unsupported release reason."))
        self._rt_lock()
        if not claim_token or claim_token != self.rt_claim_token:
            return self._rt_claim_payload("already_released")
        self._write_from_workflow(
            {
                "rt_claim_token": False,
                "rt_claimed_by_id": False,
                "rt_claimed_client_id": False,
                "rt_claimed_at": False,
                "rt_claim_expires_at": False,
                "rt_last_heartbeat_at": fields.Datetime.now(),
            }
        )
        return self._rt_claim_payload("released")

    @api.model
    def rt_recover_v1(self, client_id, limit=10):
        self._rt_validate_client_id(client_id)
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            return {"api_version": "1.0", "items": []}
        try:
            limit = max(1, min(int(limit), 25))
        except (TypeError, ValueError):
            limit = 10
        now = fields.Datetime.now()
        records = self.search(
            [
                ("agent_id", "=", self.env.user.id),
                ("state", "=", "pending"),
                ("popup_completed_at", "=", False),
                "|",
                ("rt_claim_token", "=", False),
                ("rt_claim_expires_at", "<=", now),
            ],
            order="ended_at asc, id asc",
            limit=limit,
        )
        return {
            "api_version": "1.0",
            "items": [
                {
                    "followup_id": record.id,
                    "event_id": record.event_id,
                    "title": _("Complete post-call follow-up"),
                    "message": record.name,
                }
                for record in records
            ],
        }

    @api.model
    def _cron_rt_expire_claims(self):
        now = fields.Datetime.now()
        expired = self.sudo().search(
            [
                ("state", "=", "pending"),
                ("popup_completed_at", "=", False),
                ("rt_claim_token", "!=", False),
                ("rt_claim_expires_at", "<=", now),
            ],
            limit=500,
        )
        for record in expired:
            record._write_from_workflow(
                {
                    "rt_claim_token": False,
                    "rt_claimed_by_id": False,
                    "rt_claimed_client_id": False,
                    "rt_claimed_at": False,
                    "rt_claim_expires_at": False,
                }
            )
            self.env["bus.bus"].sudo()._sendone(
                record.agent_id.partner_id,
                REALTIME_CHANNEL,
                {
                    "followup_id": record.id,
                    "event_id": record.event_id,
                    "title": _("Post-call action recovered"),
                    "message": _("A previous browser claim expired. Complete the pending follow-up."),
                },
            )
        return len(expired)
