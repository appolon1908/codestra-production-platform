from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    codestra_tenant_id = fields.Char(index=True, copy=False)


class ResUsers(models.Model):
    _inherit = "res.users"

    codestra_email_campaign_ids = fields.Many2many(
        "call.center.campaign",
        "codestra_email_user_campaign_rel",
        "user_id",
        "campaign_id",
        string="Authorized email campaigns",
        help="Explicit supervisor and campaign-manager mailbox scope.",
    )


class AgentMailboxProjection(models.Model):
    """Secret-free mailbox read model populated from verified middleware results."""
    _name = "codestra.agent.mailbox"
    _description = "Agent Campaign Mailbox"
    _order = "primary_email"

    mailbox_uuid = fields.Char(required=True, readonly=True, index=True)
    tenant_id = fields.Char(required=True, readonly=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, index=True, ondelete="restrict"
    )
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

    @api.constrains("tenant_id", "company_id", "campaign_id", "user_id", "employee_id")
    def _check_ownership(self):
        for record in self:
            if not record.company_id.codestra_tenant_id or record.tenant_id != record.company_id.codestra_tenant_id:
                raise ValidationError("Mailbox tenant must match its owning company.")
            campaign_company = getattr(record.campaign_id, "company_id", False)
            if campaign_company and campaign_company != record.company_id:
                raise ValidationError("Mailbox campaign must belong to its owning company.")
            if record.user_id and record.company_id not in record.user_id.company_ids:
                raise ValidationError("Mailbox user is not authorized for its owning company.")
            if record.employee_id and record.employee_id.company_id != record.company_id:
                raise ValidationError("Mailbox employee must belong to its owning company.")


class CampaignEmailDomainProjection(models.Model):
    _name = "codestra.campaign.email.domain"
    _description = "Approved Campaign Email Domain"

    tenant_id = fields.Char(required=True, readonly=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, index=True, ondelete="restrict"
    )
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

    @api.constrains("tenant_id", "company_id", "campaign_id")
    def _check_ownership(self):
        for record in self:
            if not record.company_id.codestra_tenant_id or record.tenant_id != record.company_id.codestra_tenant_id:
                raise ValidationError("Campaign email tenant must match its owning company.")
            campaign_company = getattr(record.campaign_id, "company_id", False)
            if campaign_company and campaign_company != record.company_id:
                raise ValidationError("Campaign email domain must belong to the campaign company.")


class AgentMailboxMessageProjection(models.Model):
    """Secret-free Klyrow message projection; bodies and attachments stay in Klyrow."""

    _name = "codestra.agent.mail.message"
    _description = "Agent Mailbox Message"
    _order = "sent_at desc, id desc"

    message_uuid = fields.Char(required=True, readonly=True, index=True)
    tenant_id = fields.Char(required=True, readonly=True, index=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True, ondelete="restrict")
    mailbox_id = fields.Many2one("codestra.agent.mailbox", required=True, readonly=True, index=True, ondelete="cascade")
    campaign_id = fields.Many2one("call.center.campaign", required=True, readonly=True, index=True, ondelete="restrict")
    thread_uuid = fields.Char(readonly=True, index=True)
    direction = fields.Selection([("INBOUND", "Inbound"), ("OUTBOUND", "Outbound")], required=True, readonly=True)
    folder = fields.Selection([
        ("INBOX", "Inbox"), ("SENT", "Sent"), ("DRAFTS", "Drafts"),
        ("FAILED", "Failed"), ("QUARANTINED", "Quarantined"),
    ], required=True, readonly=True, index=True)
    sender = fields.Char(readonly=True)
    recipients = fields.Json(readonly=True)
    subject = fields.Char(readonly=True)
    preview = fields.Char(readonly=True)
    attachment_count = fields.Integer(readonly=True)
    canonical_state = fields.Char(readonly=True, index=True)
    provider_state = fields.Char(readonly=True)
    sent_at = fields.Datetime(readonly=True, index=True)
    correlation_id = fields.Char(readonly=True, index=True)

    _message_uuid_unique = models.Constraint("unique(message_uuid)", "Message UUID must be unique.")

    @api.constrains("tenant_id", "company_id", "mailbox_id", "campaign_id")
    def _check_ownership(self):
        for record in self:
            mailbox = record.mailbox_id
            if (
                record.tenant_id != mailbox.tenant_id
                or record.company_id != mailbox.company_id
                or record.campaign_id != mailbox.campaign_id
            ):
                raise ValidationError("Message ownership must match its mailbox.")
