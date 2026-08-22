import uuid

from odoo import fields, models
from odoo.exceptions import AccessError


class CampaignControlPlaneProjection(models.Model):
    """Read model populated only from middleware reconciliation responses."""
    _name="codestra.control.plane.campaign"
    _description="Campaign synchronization dashboard"
    _order="campaign_code"

    campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="cascade",index=True)
    codestra_campaign_uuid=fields.Char(required=True,index=True,readonly=True)
    campaign_code=fields.Char(required=True,index=True,readonly=True)
    campaign_name=fields.Char(readonly=True)
    business_state=fields.Char(readonly=True)
    telephony_enabled=fields.Boolean(readonly=True)
    desired_state=fields.Char(readonly=True)
    actual_state=fields.Char(readonly=True)
    sync_status=fields.Selection([
      ("HEALTHY","Healthy"),("PENDING","Pending"),("SYNCING","Syncing"),
      ("DRIFTED","Drifted"),("FAILED","Failed"),("DEAD_LETTER","Dead Letter"),
      ("DISABLED","Disabled")],required=True,default="PENDING",readonly=True,index=True)
    odoo_status=fields.Char(readonly=True); middleware_status=fields.Char(readonly=True)
    n8n_status=fields.Char(readonly=True); vicidial_status=fields.Char(readonly=True)
    user_group=fields.Char(readonly=True); in_group=fields.Char(readonly=True)
    expected_agent_count=fields.Integer(readonly=True); actual_agent_count=fields.Integer(readonly=True)
    expected_extension_count=fields.Integer(readonly=True); actual_extension_count=fields.Integer(readonly=True)
    mapping_version=fields.Integer(readonly=True); last_sync=fields.Datetime(readonly=True)
    last_reconciliation=fields.Datetime(readonly=True)
    desired_json=fields.Json(readonly=True); actual_json=fields.Json(readonly=True)
    difference_json=fields.Json(readonly=True)
    job_id=fields.Char(readonly=True); correlation_id=fields.Char(readonly=True)

    _campaign_unique=models.Constraint("unique(campaign_id)","One control-plane projection is allowed per campaign.")

    def _require_operator(self):
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise AccessError("Control-plane operations require call-center manager access.")

    def _queue_action(self, action):
        self._require_operator()
        # The authoritative call-center module owns the reliable outbox.  This
        # method delegates to it and never calls n8n or VICIdial directly.
        for record in self:
            producer=getattr(record.campaign_id,"_enqueue_control_plane_command",None)
            if not producer:
                raise AccessError("The reliable campaign outbox is not available.")
            producer(action=action,expected_version=record.mapping_version)
        return True

    def action_validate(self): return self._queue_action("VALIDATE")
    def action_request_sync(self): return self._queue_action("REQUEST_SYNC")
    def action_reconcile(self): return self._queue_action("RECONCILE")
    def action_retry(self): return self._queue_action("RETRY_FAILED")


class CampaignControlPlaneCommand(models.Model):
    _inherit="call.center.campaign"

    def _enqueue_control_plane_command(self, *, action, expected_version):
        self.ensure_one()
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise AccessError("Control-plane commands require call-center manager access.")
        public_id=self.integration_uuid
        if not public_id:
            raise AccessError("Campaign has no immutable integration UUID.")
        correlation=str(uuid.uuid4())
        key=f"{public_id}:{expected_version}:{action}"
        return self.env["codestra.integration.outbox"].create_event(
          event_type=f"campaign.{action.lower()}.requested.v1",aggregate=self,
          aggregate_version=max(1,expected_version),correlation_id=correlation,
          idempotency_key=key,campaign=self,payload={
            "schema_version":"1","correlation_id":correlation,"idempotency_key":key,
            "tenant":self.business_unit_id.code,"event_kind":"COMMAND",
            "entity_type":"campaign","entity_id":public_id,
            "entity_version":max(1,expected_version),"action":action,
          })
