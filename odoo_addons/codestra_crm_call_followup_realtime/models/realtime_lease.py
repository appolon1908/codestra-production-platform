from __future__ import annotations

import hmac
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


LEASE_TTL_SECONDS = 120
MAX_CLIENT_INSTANCE_LENGTH = 128
MAX_CLAIM_LIMIT = 20


class CodestraCrmCallFollowup(models.Model):
    _inherit = "codestra.crm.call.followup"

    popup_lease_token = fields.Char(readonly=True, index=True, copy=False)
    popup_lease_owner = fields.Char(readonly=True, index=True, copy=False)
    popup_lease_expires_at = fields.Datetime(readonly=True, index=True, copy=False)

    @api.model
    def _require_popup_agent(self):
        if not self.env.user.has_group(
            "codestra_crm_call_followup.group_call_followup_user"
        ):
            raise AccessError(_("Call Follow-up agent access is required."))

    @api.model
    def _normalize_client_instance(self, client_instance_id):
        client_id = str(client_instance_id or "").strip()
        if not client_id:
            raise ValidationError(_("client_instance_id is required."))
        if len(client_id) > MAX_CLIENT_INSTANCE_LENGTH:
            raise ValidationError(
                _("client_instance_id cannot exceed 128 characters.")
            )
        return client_id

    @api.model
    def _normalize_claim_limit(self, limit):
        try:
            return max(1, min(int(limit), MAX_CLAIM_LIMIT))
        except (TypeError, ValueError):
            return 5

    @api.model
    def claim_pending_post_call_actions(self, client_instance_id, limit=5):
        """Atomically lease pending actions to one browser tab.

        `FOR UPDATE SKIP LOCKED` prevents two tabs or workers from claiming the
        same pending popup. An expired lease is reclaimable. A tab may refresh
        its own claim, which replaces the prior token and invalidates stale UI.
        """
        self._require_popup_agent()
        client_id = self._normalize_client_instance(client_instance_id)
        limit = self._normalize_claim_limit(limit)
        now = fields.Datetime.now()
        company_ids = self.env.companies.ids
        if not company_ids:
            return []

        self.env.cr.execute(
            """
            SELECT id
              FROM codestra_crm_call_followup
             WHERE agent_id = %s
               AND company_id = ANY(%s)
               AND state = 'pending'
               AND popup_completed_at IS NULL
               AND (snoozed_until IS NULL OR snoozed_until <= %s)
               AND (
                    popup_lease_expires_at IS NULL
                    OR popup_lease_expires_at <= %s
                    OR popup_lease_owner = %s
               )
             ORDER BY priority_rank DESC, ended_at ASC, id ASC
             LIMIT %s
             FOR UPDATE SKIP LOCKED
            """,
            [
                self.env.user.id,
                company_ids,
                now,
                now,
                client_id,
                limit,
            ],
        )
        records = self.browse([row[0] for row in self.env.cr.fetchall()]).exists()
        expires_at = now + timedelta(seconds=LEASE_TTL_SECONDS)
        claimed = []
        for record in records:
            token = uuid.uuid4().hex
            record._write_from_workflow(
                {
                    "popup_lease_token": token,
                    "popup_lease_owner": client_id,
                    "popup_lease_expires_at": expires_at,
                }
            )
            claimed.append(
                {
                    "followup_id": record.id,
                    "event_id": record.event_id,
                    "priority": record.priority,
                    "title": _("Complete post-call follow-up"),
                    "message": record.name,
                    "lease_token": token,
                    "lease_expires_at": fields.Datetime.to_string(expires_at),
                }
            )
        return claimed

    def _validate_popup_lease(self, client_instance_id, lease_token):
        self.ensure_one()
        client_id = self._normalize_client_instance(client_instance_id)
        supplied = str(lease_token or "").strip()
        current = self.popup_lease_token or ""
        if not supplied or not current or not hmac.compare_digest(current, supplied):
            raise AccessError(_("The popup lease token is invalid or stale."))
        if self.popup_lease_owner != client_id:
            raise AccessError(_("This popup lease belongs to another browser tab."))
        if not self.popup_lease_expires_at or self.popup_lease_expires_at <= fields.Datetime.now():
            raise AccessError(_("This popup lease has expired."))
        if self.agent_id != self.env.user:
            raise AccessError(_("Only the assigned agent may manage this popup lease."))
        if self.company_id not in self.env.companies:
            raise AccessError(_("The popup belongs to another active company scope."))
        if self.state != "pending" or self.popup_completed_at:
            raise ValidationError(_("This post-call action is no longer pending."))
        return client_id

    def renew_popup_lease(self, client_instance_id, lease_token):
        self._require_popup_agent()
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM codestra_crm_call_followup WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()
        self._validate_popup_lease(client_instance_id, lease_token)
        expires_at = fields.Datetime.now() + timedelta(seconds=LEASE_TTL_SECONDS)
        self._write_from_workflow({"popup_lease_expires_at": expires_at})
        return {
            "followup_id": self.id,
            "lease_token": lease_token,
            "lease_expires_at": fields.Datetime.to_string(expires_at),
        }

    def release_popup_lease(self, client_instance_id, lease_token):
        self._require_popup_agent()
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM codestra_crm_call_followup WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()
        self._validate_popup_lease(client_instance_id, lease_token)
        self._write_from_workflow(
            {
                "popup_lease_token": False,
                "popup_lease_owner": False,
                "popup_lease_expires_at": False,
            }
        )
        return True

    def _write_from_workflow(self, values):
        values = dict(values)
        if (
            values.get("state") in {"completed", "cancelled"}
            or values.get("popup_completed_at")
            or values.get("snoozed_until")
        ):
            values.update(
                {
                    "popup_lease_token": False,
                    "popup_lease_owner": False,
                    "popup_lease_expires_at": False,
                }
            )
        return super()._write_from_workflow(values)
