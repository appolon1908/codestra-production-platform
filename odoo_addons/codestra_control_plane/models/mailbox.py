from odoo import fields, models


class AgentMailboxProjection(models.Model):
    """Secret-free mailbox read model populated from verified middleware results."""
    _name = "codestra.agent.mailbox"
    _description = "Agent Campaign Mailbox"
    _order = "primary_email"

    mailbox_uuid = fields.Char(required=True, readonly=True, index=True)
    agent_uuid = fields.Char(required=True, readonly=True, index=True)
    employee_id = fields.Many2one("hr.employee", readonly=True, ondelete="set null")
    user_id = fields.Many2one("res.users", readonly=True, ondelete="set null")
    campaign_id = fields.Many2one("call.center.campaign", required=True, readonly=True, ondelete="restrict")
    campaign_name = fields.Char(readonly=True)
    domain = fields.Char(required=True, readonly=True)
    primary_email = fields.Char(required=True, readonly=True, index=True)
    display_name = fields.Char(readonly=True)
    mailbox_status = fields.Selection([
        ("BLOCKED_DOMAIN_MAPPING_REQUIRED", "Domain Mapping Required"),
        ("EMAIL_ADDRESS_CONFLICT", "Address Conflict"),
        ("PROVISIONING", "Provisioning"),
        ("ACTIVE", "Active"),
        ("PROVISIONING_FAILED", "Provisioning Failed"),
        ("SUSPENDED", "Suspended"),
        ("DEACTIVATED", "Deactivated"),
    ], required=True, readonly=True, index=True)
    sending_enabled = fields.Boolean(readonly=True)
    receiving_enabled = fields.Boolean(readonly=True)
    quota = fields.Integer(readonly=True)
    usage = fields.Integer(readonly=True)
    last_sync = fields.Datetime(readonly=True)
    last_send_at = fields.Datetime(readonly=True)
    last_receive_at = fields.Datetime(readonly=True)
    failure_reason_safe = fields.Char(readonly=True)
    correlation_id = fields.Char(readonly=True)
    audit_version = fields.Integer(readonly=True)

    _mailbox_uuid_unique = models.Constraint("unique(mailbox_uuid)", "Mailbox UUID must be unique.")
    _mailbox_address_unique = models.Constraint("unique(primary_email)", "Mailbox address must be unique.")


class CampaignEmailDomainProjection(models.Model):
    _name = "codestra.campaign.email.domain"
    _description = "Approved Campaign Email Domain"

    campaign_id = fields.Many2one("call.center.campaign", required=True, readonly=True, ondelete="restrict")
    primary_domain = fields.Char(required=True, readonly=True)
    alias_domains = fields.Json(readonly=True)
    sender_domain_verified = fields.Boolean(readonly=True)
    inbound_domain_verified = fields.Boolean(readonly=True)
    sending_enabled = fields.Boolean(readonly=True)
    receiving_enabled = fields.Boolean(readonly=True)
    support_address = fields.Char(readonly=True)
    billing_address = fields.Char(readonly=True)
    status = fields.Selection([
        ("UNVERIFIED", "Unverified"), ("ACTIVE", "Active"),
        ("SUSPENDED", "Suspended"), ("REVOKED", "Revoked"),
    ], required=True, readonly=True)
    approved_by = fields.Char(readonly=True)
    approved_at = fields.Datetime(readonly=True)

    _campaign_domain_unique = models.Constraint("unique(campaign_id)", "Campaign domain mapping must be unique.")
