from odoo import api, models


class CodestraCrmCallFollowupRealtimeApi(models.AbstractModel):
    _name = "codestra.crm.call.followup.realtime.api"
    _description = "CRM Call Follow-up Realtime API"

    @api.model
    def capabilities_v1(self):
        return {
            "api_version": "1.0",
            "claim_lease_seconds": {"minimum": 30, "default": 90, "maximum": 300},
            "recovery_limit": {"default": 10, "maximum": 25},
            "features": [
                "assigned-agent-claim",
                "multi-tab-exclusion",
                "heartbeat-renewal",
                "browser-reconnect-recovery",
                "expired-claim-redelivery",
            ],
        }

    @api.model
    def claim_v1(self, followup_id, client_id, lease_seconds=90):
        record = self.env["codestra.crm.call.followup"].browse(int(followup_id)).exists()
        if not record:
            return {"api_version": "1.0", "status": "not_found", "followup_id": False}
        return record.rt_claim_v1(client_id, lease_seconds=lease_seconds)

    @api.model
    def acknowledge_opened_v1(self, followup_id, claim_token):
        record = self.env["codestra.crm.call.followup"].browse(int(followup_id)).exists()
        if not record:
            return {"api_version": "1.0", "status": "not_found", "followup_id": False}
        return record.rt_ack_opened_v1(claim_token)

    @api.model
    def renew_v1(self, followup_id, claim_token, lease_seconds=90):
        record = self.env["codestra.crm.call.followup"].browse(int(followup_id)).exists()
        if not record:
            return {"api_version": "1.0", "status": "not_found", "followup_id": False}
        return record.rt_renew_v1(claim_token, lease_seconds=lease_seconds)

    @api.model
    def release_v1(self, followup_id, claim_token, reason="closed"):
        record = self.env["codestra.crm.call.followup"].browse(int(followup_id)).exists()
        if not record:
            return {"api_version": "1.0", "status": "not_found", "followup_id": False}
        return record.rt_release_v1(claim_token, reason=reason)

    @api.model
    def recover_v1(self, client_id, limit=10):
        return self.env["codestra.crm.call.followup"].rt_recover_v1(
            client_id,
            limit=limit,
        )
