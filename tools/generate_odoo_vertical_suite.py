#!/usr/bin/env python3
"""Generate the Codestra-owned Odoo 19 vertical suite.

The generated modules deliberately share one organizational/security foundation.
No module introduces a competing CRM, company, campaign, or call-center core.
"""

from pathlib import Path
from textwrap import dedent


ROOT = Path("/opt/codestra/odoo19-vertical-addons")

GROUPS = {
    "transport": [
        "codestra_transportation_crm", "codestra_shipper_carrier",
        "codestra_load_management", "codestra_rate_quote", "codestra_dispatch",
        "codestra_equipment_management", "codestra_authority_insurance",
        "codestra_transport_followup", "codestra_transport_reporting",
    ],
    "loan": [
        "codestra_loan_origination", "codestra_borrower_profile",
        "codestra_loan_application", "codestra_document_checklist",
        "codestra_underwriting_workflow", "codestra_approval_audit",
        "codestra_payment_plan", "codestra_collections",
        "codestra_lending_compliance", "codestra_loan_reporting",
    ],
    "student": [
        "codestra_student_repayment", "codestra_servicer_case",
        "codestra_repayment_plan", "codestra_hardship_assistance",
        "codestra_document_verification", "codestra_payment_followup",
        "codestra_student_consent", "codestra_repayment_compliance",
    ],
    "services": [
        "codestra_service_intake", "codestra_project_scoping",
        "codestra_proposal_management", "codestra_client_requirements",
        "codestra_project_handoff", "codestra_web_development",
        "codestra_app_development", "codestra_ai_services",
        "codestra_client_success", "codestra_service_renewal",
    ],
    "senior": [
        "codestra_senior_products", "codestra_caregiver_contact",
        "codestra_accessibility_needs", "codestra_product_recommendation",
        "codestra_delivery_followup", "codestra_product_consent",
        "codestra_returns_retention", "codestra_senior_customer_protection",
    ],
}

OFFICIAL = {
    "transport": ["crm", "sale_management", "project", "fleet", "purchase", "stock", "delivery", "account"],
    "loan": ["contacts", "crm", "account", "sale_management", "calendar", "survey", "website_crm", "project"],
    "student": ["crm", "account", "calendar", "survey", "project"],
    "services": ["crm", "sale_management", "project", "hr_timesheet", "account", "website", "website_crm", "survey", "mass_mailing"],
    "senior": ["crm", "sale_management", "stock", "purchase", "delivery", "account", "website", "website_sale", "survey", "mass_mailing", "repair", "maintenance"],
}


def write(relative: str, body: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).lstrip(), encoding="utf-8")


def manifest(name: str, depends: list[str], data: list[str] | None = None, application: bool = False) -> str:
    return repr({
        "name": name.replace("_", " ").title(),
        "version": "19.0.1.0.0",
        "category": "Codestra/Vertical Operations",
        "summary": f"Codestra-owned capability: {name}",
        "author": "Codestra",
        "license": "LGPL-3",
        "depends": depends,
        "data": data or [],
        "installable": True,
        "application": application,
    }) + "\n"


write("codestra_vertical_core/__init__.py", "from . import models\n")
write("codestra_vertical_core/models/__init__.py", """
from . import core
from . import integration
""")
write("codestra_vertical_core/__manifest__.py", manifest(
    "codestra_vertical_core",
    ["call_center_core", "call_center_campaign", "call_center_compliance", "crm", "mail"],
    ["security/groups.xml", "security/ir.model.access.csv", "security/rules.xml", "data/pipeline_stages.xml", "views/core_views.xml"],
    True,
))
write("codestra_vertical_core/models/core.py", r'''
import json
from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CodestraVerticalMixin(models.AbstractModel):
    _name = "codestra.vertical.mixin"
    _description = "Codestra Vertical Scope and Audit Fields"
    _inherit = ["mail.thread", "mail.activity.mixin", "call.center.business.unit.mixin"]

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, tracking=True,
    )
    campaign_id = fields.Many2one("call.center.campaign", index=True, tracking=True)
    operational_team_id = fields.Many2one("call.center.team", index=True, tracking=True)
    owner_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, index=True, tracking=True,
    )
    consent_state = fields.Selection(
        [("unknown", "Unknown"), ("missing", "Missing"), ("granted", "Granted"),
         ("revoked", "Revoked")], required=True, default="unknown", tracking=True,
    )
    dnc_state = fields.Selection(
        [("unknown", "Unknown"), ("allowed", "Allowed"), ("listed", "Listed"),
         ("unavailable", "Service Unavailable")],
        required=True, default="unknown", tracking=True,
    )
    lifecycle_state = fields.Selection(
        [("draft", "Draft"), ("active", "Active"), ("hold", "Compliance Hold"),
         ("complete", "Complete"), ("cancelled", "Cancelled")],
        required=True, default="draft", tracking=True,
    )
    source_system = fields.Char(default="odoo", index=True)
    external_reference = fields.Char(index=True)
    idempotency_key = fields.Char(index=True, copy=False)
    active = fields.Boolean(default=True, tracking=True)

    @api.constrains("company_id", "business_unit_id", "campaign_id", "operational_team_id")
    def _check_vertical_scope(self):
        for record in self:
            if record.business_unit_id and record.business_unit_id.company_id != record.company_id:
                raise ValidationError("Business unit and company must match.")
            for scoped in (record.campaign_id, record.operational_team_id):
                if scoped and scoped.business_unit_id != record.business_unit_id:
                    raise ValidationError("Campaign/team must belong to the selected business unit.")

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        for vals in vals_list:
            key = vals.get("idempotency_key")
            if key:
                existing = self.search([("idempotency_key", "=", key)], limit=1)
                if existing:
                    records |= existing
                    continue
            records |= super(CodestraVerticalMixin, self).create([vals])
        return records


class CodestraVerticalAudit(models.Model):
    _name = "codestra.vertical.audit"
    _description = "Immutable Vertical Audit Event"
    _order = "event_at desc, id desc"

    event_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, readonly=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    business_unit_id = fields.Many2one("call.center.business.unit", readonly=True, index=True)
    campaign_id = fields.Many2one("call.center.campaign", readonly=True, index=True)
    model_name = fields.Char(required=True, readonly=True, index=True)
    record_id = fields.Integer(required=True, readonly=True, index=True)
    action = fields.Char(required=True, readonly=True)
    prior_state = fields.Char(readonly=True)
    new_state = fields.Char(readonly=True)
    audit_reference = fields.Char(required=True, readonly=True, index=True)
    payload_digest = fields.Char(readonly=True)

    def write(self, vals):
        raise AccessError("Audit records are immutable.")

    def unlink(self):
        raise AccessError("Audit records are immutable.")


class CrmStage(models.Model):
    _inherit = "crm.stage"

    codestra_vertical = fields.Selection([
        ("transportation", "Transportation"), ("moneybee", "Moneybee Loans"),
        ("student", "Student Repayment"), ("services", "Services"),
        ("senior", "Senior Products"),
    ], index=True)
    campaign_ids = fields.Many2many("call.center.campaign", string="Permitted Campaigns")
    allowed_next_stage_ids = fields.Many2many(
        "crm.stage", "codestra_stage_transition_rel", "from_stage_id", "to_stage_id",
        string="Allowed Next Stages",
    )

class CallCenterCampaign(models.Model):
    _inherit = "call.center.campaign"

    codestra_vertical = fields.Selection([
        ("transportation", "Transportation"), ("moneybee", "Moneybee Loans"),
        ("student", "Student Repayment"), ("services", "Services"),
        ("senior", "Senior Products"),
    ], index=True, tracking=True)


class CallCenterPipeline(models.Model):
    _inherit = "call.center.pipeline"

    codestra_vertical = fields.Selection([
        ("transportation", "Transportation"), ("moneybee", "Moneybee Loans"),
        ("student", "Student Repayment"), ("services", "Services"),
        ("senior", "Senior Products"),
    ], index=True, tracking=True)


class CrmLead(models.Model):
    _inherit = "crm.lead"

    codestra_vertical = fields.Selection([
        ("transportation", "Transportation"), ("moneybee", "Moneybee Loans"),
        ("student", "Student Repayment"), ("services", "Services"),
        ("senior", "Senior Products"),
    ], index=True, tracking=True)
    vertical_idempotency_key = fields.Char(index=True, copy=False)

    def write(self, vals):
        if "stage_id" in vals:
            target = self.env["crm.stage"].browse(vals["stage_id"])
            for lead in self:
                if lead.codestra_vertical and lead.stage_id.allowed_next_stage_ids and target not in lead.stage_id.allowed_next_stage_ids:
                    raise ValidationError("This campaign pipeline transition is not allowed.")
                if target.campaign_ids and lead.call_center_campaign_id not in target.campaign_ids:
                    raise ValidationError("The target stage is not permitted for this campaign.")
                campaign_vertical = lead.call_center_campaign_id.codestra_vertical
                if campaign_vertical and target.codestra_vertical != campaign_vertical:
                    raise ValidationError("The target stage belongs to another campaign vertical.")
        prior = {lead.id: lead.stage_id.display_name for lead in self} if "stage_id" in vals else {}
        result = super().write(vals)
        if prior:
            Audit = self.env["codestra.vertical.audit"].sudo()
            for lead in self:
                Audit.create({
                    "company_id": lead.company_id.id,
                    "business_unit_id": lead.business_unit_id.id,
                    "campaign_id": lead.call_center_campaign_id.id,
                    "model_name": lead._name, "record_id": lead.id,
                    "action": "stage_transition", "prior_state": prior[lead.id],
                    "new_state": lead.stage_id.display_name,
                    "audit_reference": f"crm.lead:{lead.id}:{fields.Datetime.now()}",
                })
        return result
''')
write("codestra_vertical_core/models/integration.py", r'''
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CodestraIntegrationEvent(models.Model):
    _name = "codestra.integration.event"
    _description = "Inactive Staging Integration Contract Event"
    _inherit = "codestra.vertical.mixin"

    event_id = fields.Char(required=True, index=True)
    schema_version = fields.Char(required=True, default="1.0")
    event_type = fields.Selection([
        ("lead.create", "Lead Creation"), ("lead.update", "Lead Update"),
        ("assignment", "Assignment"), ("stage.transition", "Stage Transition"),
        ("appointment", "Appointment"), ("callback", "Callback"),
        ("sale.confirmation", "Sale Confirmation"), ("project.creation", "Project Creation"),
        ("document.request", "Document Request"), ("underwriting.update", "Underwriting Update"),
        ("repayment.followup", "Repayment Follow-Up"), ("dispatch.update", "Dispatch Update"),
        ("delivery.update", "Delivery Update"), ("compliance.hold", "Compliance Hold"),
        ("consent.change", "Consent Change"), ("dnc.change", "DNC Change"),
        ("reporting.event", "Reporting Event"),
    ], required=True, index=True)
    event_timestamp = fields.Datetime(required=True)
    record_model = fields.Char(required=True)
    record_reference = fields.Char(required=True)
    audit_reference = fields.Char(required=True)
    payload_json = fields.Text(default="{}")
    delivery_enabled = fields.Boolean(default=False, readonly=True)
    state = fields.Selection([("inactive", "Inactive"), ("validated", "Validated")], default="inactive", required=True)

    _event_id_unique = models.Constraint("unique(event_id)", "Event IDs must be unique.")
    _event_idempotency_unique = models.Constraint("unique(idempotency_key)", "Idempotency keys must be unique.")

    @api.constrains("delivery_enabled")
    def _check_no_delivery(self):
        if any(self.mapped("delivery_enabled")):
            raise ValidationError("Production delivery is disabled for staging contracts.")
''')
write("codestra_vertical_core/security/groups.xml", r'''
<odoo>
  <record id="group_vertical_agent" model="res.groups"><field name="name">Vertical Agent</field><field name="implied_ids" eval="[(4, ref('call_center_core.group_call_center_agent'))]"/></record>
  <record id="group_vertical_operations" model="res.groups"><field name="name">Vertical Operations</field><field name="implied_ids" eval="[(4, ref('call_center_core.group_call_center_supervisor'))]"/></record>
  <record id="group_vertical_auditor" model="res.groups"><field name="name">Vertical Auditor</field><field name="implied_ids" eval="[(4, ref('call_center_core.group_call_center_user'))]"/></record>
  <record id="group_vertical_integration" model="res.groups"><field name="name">Vertical Integration Service</field><field name="implied_ids" eval="[(4, ref('call_center_core.group_call_center_user'))]"/></record>
  <record id="group_loan_agent" model="res.groups"><field name="name">Loan Agent</field><field name="implied_ids" eval="[(4, ref('group_vertical_agent'))]"/></record>
  <record id="group_loan_underwriter" model="res.groups"><field name="name">Loan Underwriter</field><field name="implied_ids" eval="[(4, ref('call_center_core.group_call_center_compliance'))]"/></record>
  <record id="group_loan_finance" model="res.groups"><field name="name">Loan Finance</field><field name="implied_ids" eval="[(4, ref('call_center_core.group_call_center_finance'))]"/></record>
  <record id="group_student_agent" model="res.groups"><field name="name">Student Repayment Agent</field><field name="implied_ids" eval="[(4, ref('group_vertical_agent'))]"/></record>
  <record id="group_student_compliance" model="res.groups"><field name="name">Student Repayment Compliance</field><field name="implied_ids" eval="[(4, ref('call_center_core.group_call_center_compliance'))]"/></record>
  <record id="group_senior_protection" model="res.groups"><field name="name">Senior Customer Protection</field><field name="implied_ids" eval="[(4, ref('call_center_core.group_call_center_compliance'))]"/></record>
</odoo>
''')
write("codestra_vertical_core/security/ir.model.access.csv", """id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_vertical_audit_user,vertical audit user,model_codestra_vertical_audit,group_vertical_auditor,1,0,0,0
access_vertical_audit_admin,vertical audit admin,model_codestra_vertical_audit,call_center_core.group_call_center_admin,1,0,1,0
access_integration_event_service,integration event service,model_codestra_integration_event,group_vertical_integration,1,1,1,0
access_integration_event_admin,integration event admin,model_codestra_integration_event,call_center_core.group_call_center_admin,1,1,1,1
""")
write("codestra_vertical_core/security/rules.xml", r'''
<odoo>
  <record id="rule_vertical_audit_scope" model="ir.rule">
    <field name="name">Vertical audit authorized business units</field>
    <field name="model_id" ref="model_codestra_vertical_audit"/>
    <field name="groups" eval="[(4, ref('group_vertical_auditor'))]"/>
    <field name="domain_force">[('business_unit_id', 'in', user.call_center_business_unit_ids.ids)]</field>
  </record>
  <record id="rule_integration_event_scope" model="ir.rule">
    <field name="name">Integration events authorized business units</field>
    <field name="model_id" ref="model_codestra_integration_event"/>
    <field name="groups" eval="[(4, ref('group_vertical_integration'))]"/>
    <field name="domain_force">[('business_unit_id', 'in', user.call_center_business_unit_ids.ids)]</field>
  </record>
</odoo>
''')
write("codestra_vertical_core/views/core_views.xml", r'''
<odoo>
  <record id="view_vertical_audit_list" model="ir.ui.view">
    <field name="name">codestra.vertical.audit.list</field><field name="model">codestra.vertical.audit</field>
    <field name="arch" type="xml"><list create="false" edit="false" delete="false"><field name="event_at"/><field name="model_name"/><field name="record_id"/><field name="action"/><field name="audit_reference"/></list></field>
  </record>
  <record id="action_vertical_audit" model="ir.actions.act_window"><field name="name">Vertical Audit</field><field name="res_model">codestra.vertical.audit</field><field name="view_mode">list</field></record>
  <menuitem id="menu_codestra_vertical_root" name="Codestra Verticals" sequence="65" groups="call_center_core.group_call_center_user"/>
  <menuitem id="menu_vertical_audit" parent="menu_codestra_vertical_root" action="action_vertical_audit" sequence="90" groups="codestra_vertical_core.group_vertical_auditor"/>
</odoo>
''')
write("codestra_vertical_core/data/safety.xml", r'''
<odoo noupdate="0">
  <record id="flag_external_delivery" model="ir.config_parameter"><field name="key">ENABLE_EXTERNAL_DELIVERY</field><field name="value">false</field></record>
  <record id="flag_live_calls" model="ir.config_parameter"><field name="key">ALLOW_LIVE_CALLS</field><field name="value">false</field></record>
  <record id="flag_live_email" model="ir.config_parameter"><field name="key">ALLOW_LIVE_EMAIL</field><field name="value">false</field></record>
  <record id="flag_live_sms" model="ir.config_parameter"><field name="key">ALLOW_LIVE_SMS</field><field name="value">false</field></record>
  <record id="flag_campaign_activation" model="ir.config_parameter"><field name="key">ALLOW_CAMPAIGN_ACTIVATION</field><field name="value">false</field></record>
</odoo>
''')


ANCHOR_MODELS = {
"transport": r'''
from odoo import api, fields, models
from odoo.exceptions import ValidationError

class ResPartner(models.Model):
    _inherit = "res.partner"
    transport_role = fields.Selection([("shipper","Shipper"),("carrier","Carrier"),("broker","Broker"),("driver","Driver")], index=True)
    authority_number = fields.Char(index=True)
    insurance_expiration = fields.Date()
    transport_compliance_state = fields.Selection([("pending","Pending"),("approved","Approved"),("expired","Expired"),("hold","Hold")], default="pending")

class CrmLead(models.Model):
    _inherit = "crm.lead"
    freight_type = fields.Char()
    equipment_type = fields.Char()
    estimated_volume = fields.Float()
    load_frequency = fields.Char()
    transport_target_rate = fields.Monetary(currency_field="company_currency")

class TransportLane(models.Model):
    _name = "codestra.transport.lane"; _description = "Transportation Lane"; _inherit = "codestra.vertical.mixin"
    name = fields.Char(required=True); origin = fields.Char(required=True); destination = fields.Char(required=True)
    freight_type = fields.Char(); equipment_type = fields.Char(); load_frequency = fields.Char()
    estimated_volume = fields.Float(); target_rate = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", required=True, default=lambda s:s.env.company.currency_id)

class TransportLoad(models.Model):
    _name = "codestra.transport.load"; _description = "Transportation Load"; _inherit = "codestra.vertical.mixin"
    name = fields.Char(required=True, index=True); lane_id = fields.Many2one("codestra.transport.lane", required=True)
    shipper_id = fields.Many2one("res.partner", required=True); carrier_id = fields.Many2one("res.partner")
    driver_id = fields.Many2one("res.partner"); equipment_id = fields.Many2one("fleet.vehicle")
    pickup_at = fields.Datetime(); delivered_at = fields.Datetime()
    load_state = fields.Selection([("draft","Draft"),("quoted","Quoted"),("assigned","Assigned"),("picked_up","Picked Up"),("delivered","Delivered"),("cancelled","Cancelled")], default="draft", required=True, tracking=True)
    quoted_rate = fields.Monetary(currency_field="currency_id"); accepted_rate = fields.Monetary(currency_field="currency_id")
    cost_amount = fields.Monetary(currency_field="currency_id"); profitability = fields.Monetary(compute="_compute_profit", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", required=True, default=lambda s:s.env.company.currency_id)
    @api.depends("accepted_rate","cost_amount")
    def _compute_profit(self):
        for rec in self: rec.profitability = rec.accepted_rate - rec.cost_amount

class TransportQuote(models.Model):
    _name = "codestra.transport.quote"; _description = "Transportation Rate Quote"; _inherit = "codestra.vertical.mixin"
    name = fields.Char(required=True); load_id = fields.Many2one("codestra.transport.load", required=True)
    quoted_rate = fields.Monetary(required=True, currency_field="currency_id"); accepted_rate = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", required=True, default=lambda s:s.env.company.currency_id)
    quote_state = fields.Selection([("draft","Draft"),("sent","Sent"),("accepted","Accepted"),("rejected","Rejected")], default="draft", required=True)

class TransportDispatch(models.Model):
    _name = "codestra.transport.dispatch"; _description = "Dispatch Assignment"; _inherit = "codestra.vertical.mixin"
    load_id = fields.Many2one("codestra.transport.load", required=True, ondelete="cascade")
    carrier_id = fields.Many2one("res.partner", required=True); driver_id = fields.Many2one("res.partner")
    assigned_at = fields.Datetime(default=fields.Datetime.now, required=True); notes = fields.Text()

class TransportInsurance(models.Model):
    _name = "codestra.transport.insurance"; _description = "Carrier Authority and Insurance"; _inherit = "codestra.vertical.mixin"
    carrier_id = fields.Many2one("res.partner", required=True); authority_number = fields.Char(required=True)
    policy_number = fields.Char(required=True); expires_on = fields.Date(required=True)
    compliance_state = fields.Selection([("pending","Pending"),("approved","Approved"),("expired","Expired"),("hold","Hold")], default="pending", required=True)
''',
"loan": r'''
from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

class BorrowerProfile(models.Model):
    _name = "codestra.borrower.profile"; _description = "Secured Borrower Profile"; _inherit = "codestra.vertical.mixin"
    partner_id = fields.Many2one("res.partner", required=True, index=True)
    disclosure_acknowledged = fields.Boolean(tracking=True); disclosure_at = fields.Datetime(readonly=True)
    household_income = fields.Monetary(groups="codestra_vertical_core.group_loan_underwriter,codestra_vertical_core.group_loan_finance", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", required=True, default=lambda s:s.env.company.currency_id)

class LoanApplication(models.Model):
    _name = "codestra.loan.application"; _description = "Secured Loan Application"; _inherit = "codestra.vertical.mixin"
    name = fields.Char(required=True, index=True); borrower_id = fields.Many2one("codestra.borrower.profile", required=True)
    requested_amount = fields.Monetary(required=True, currency_field="currency_id")
    approved_amount = fields.Monetary(groups="codestra_vertical_core.group_loan_underwriter,codestra_vertical_core.group_loan_finance", currency_field="currency_id")
    outstanding_balance = fields.Monetary(groups="codestra_vertical_core.group_loan_finance", currency_field="currency_id")
    term_months = fields.Integer(); annual_rate = fields.Float(groups="codestra_vertical_core.group_loan_underwriter,codestra_vertical_core.group_loan_finance")
    currency_id = fields.Many2one("res.currency", required=True, default=lambda s:s.env.company.currency_id)
    application_state = fields.Selection([("new","New Application"),("started","Application Started"),("documents","Documents Pending"),("underwriting","Underwriting"),("conditional","Conditional Approval"),("approved","Approved"),("declined","Declined"),("funded","Funded/Completed")], default="new", required=True, tracking=True)
    decision_reason = fields.Text(groups="codestra_vertical_core.group_loan_underwriter")
    conditions = fields.Text(groups="codestra_vertical_core.group_loan_underwriter")
    disbursement_reference = fields.Char(groups="codestra_vertical_core.group_loan_finance")
    def write(self, vals):
        old = {r.id:r.application_state for r in self}
        result = super().write(vals)
        if "application_state" in vals and vals["application_state"] in ("approved","declined"):
            for rec in self:
                self.env["codestra.loan.decision.audit"].sudo().create({"application_id":rec.id,"decision":rec.application_state,"prior_state":old[rec.id],"reason":vals.get("decision_reason") or rec.decision_reason})
        return result

class LoanDecisionAudit(models.Model):
    _name = "codestra.loan.decision.audit"; _description = "Immutable Loan Decision Audit"; _order = "decided_at desc"
    application_id = fields.Many2one("codestra.loan.application", required=True, ondelete="restrict", readonly=True)
    decision = fields.Selection([("approved","Approved"),("declined","Declined")], required=True, readonly=True)
    prior_state = fields.Char(readonly=True); reason = fields.Text(readonly=True)
    decided_by = fields.Many2one("res.users", required=True, default=lambda s:s.env.user, readonly=True)
    decided_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    def write(self, vals): raise AccessError("Loan decision audit is immutable.")
    def unlink(self): raise AccessError("Loan decision audit is immutable.")

class LoanDocument(models.Model):
    _name = "codestra.loan.document"; _description = "Loan Document Checklist"; _inherit = "codestra.vertical.mixin"
    application_id = fields.Many2one("codestra.loan.application", required=True, ondelete="cascade")
    document_type = fields.Char(required=True); received = fields.Boolean(); verified = fields.Boolean(groups="codestra_vertical_core.group_loan_underwriter")
    attachment_id = fields.Many2one("ir.attachment")

class LoanPaymentSchedule(models.Model):
    _name = "codestra.loan.payment.schedule"; _description = "Loan Payment Schedule"; _inherit = "codestra.vertical.mixin"
    application_id = fields.Many2one("codestra.loan.application", required=True, ondelete="restrict")
    due_date = fields.Date(required=True); amount_due = fields.Monetary(required=True, currency_field="currency_id"); amount_paid = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="application_id.currency_id", store=True)
    payment_state = fields.Selection([("scheduled","Scheduled"),("paid","Paid"),("late","Late"),("waived","Waived")], default="scheduled", required=True)

class LoanCollectionCase(models.Model):
    _name = "codestra.loan.collection"; _description = "Loan Collection Case"; _inherit = "codestra.vertical.mixin"
    application_id = fields.Many2one("codestra.loan.application", required=True); delinquent_since = fields.Date(required=True)
    amount_delinquent = fields.Monetary(currency_field="currency_id"); currency_id = fields.Many2one("res.currency", related="application_id.currency_id", store=True)
    notes = fields.Text(groups="codestra_vertical_core.group_loan_finance")
''',
"student": r'''
from odoo import fields, models

class StudentServicerCase(models.Model):
    _name = "codestra.student.servicer.case"; _description = "Student Repayment Servicer Case"; _inherit = "codestra.vertical.mixin"
    name = fields.Char(required=True); student_id = fields.Many2one("res.partner", required=True)
    servicer_id = fields.Many2one("res.partner", required=True); current_plan = fields.Char()
    proposed_plan = fields.Char(); hardship_type = fields.Char()
    household_information = fields.Text(groups="codestra_vertical_core.group_student_compliance")
    income_document_id = fields.Many2one("ir.attachment", groups="codestra_vertical_core.group_student_compliance")
    assistance_eligibility = fields.Selection([("unknown","Unknown"),("eligible","Eligible"),("ineligible","Ineligible"),("review","Review")], default="unknown")
    followup_at = fields.Datetime(); disclosure_acknowledged = fields.Boolean(); outcome = fields.Char()
    case_state = fields.Selection([("new","New Case"),("contacted","Contacted"),("servicer","Servicer Verification"),("assessment","Needs Assessment"),("documents","Documents Pending"),("review","Repayment Plan Review"),("submitted","Assistance Submitted"),("followup","Follow-Up"),("resolved","Resolved"),("closed","Closed")], default="new", required=True, tracking=True)

class StudentRepaymentPlan(models.Model):
    _name = "codestra.student.repayment.plan"; _description = "Student Repayment Plan"; _inherit = "codestra.vertical.mixin"
    case_id = fields.Many2one("codestra.student.servicer.case", required=True, ondelete="cascade")
    name = fields.Char(required=True); monthly_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", required=True, default=lambda s:s.env.company.currency_id)
    start_date = fields.Date(); plan_state = fields.Selection([("proposed","Proposed"),("submitted","Submitted"),("accepted","Accepted"),("rejected","Rejected")], default="proposed", required=True)

class StudentDocumentVerification(models.Model):
    _name = "codestra.student.document.verification"; _description = "Student Document Verification"; _inherit = "codestra.vertical.mixin"
    case_id = fields.Many2one("codestra.student.servicer.case", required=True, ondelete="cascade")
    document_type = fields.Char(required=True); attachment_id = fields.Many2one("ir.attachment")
    verification_state = fields.Selection([("pending","Pending"),("verified","Verified"),("rejected","Rejected")], default="pending", required=True)
    reviewer_id = fields.Many2one("res.users", groups="codestra_vertical_core.group_student_compliance")
''',
"services": r'''
from odoo import api, fields, models

class ServiceIntake(models.Model):
    _name = "codestra.service.intake"; _description = "Service Intake"; _inherit = "codestra.vertical.mixin"
    name = fields.Char(required=True); lead_id = fields.Many2one("crm.lead", required=True)
    service_type = fields.Selection([("web","Web Development"),("app","App Development"),("ai","AI Services")], required=True)
    requirements = fields.Text(); scope = fields.Text(); acceptance_criteria = fields.Text()
    proposal_id = fields.Many2one("sale.order"); delivery_team_id = fields.Many2one("project.project")

class SaleOrder(models.Model):
    _inherit = "sale.order"
    codestra_service_intake_id = fields.Many2one("codestra.service.intake", copy=False)
    codestra_project_id = fields.Many2one("project.project", copy=False)
    def action_confirm(self):
        orders_to_confirm = self.filtered(lambda order: order.state in ("draft", "sent"))
        result = (
            super(SaleOrder, orders_to_confirm).action_confirm()
            if orders_to_confirm else True
        )
        for order in self.filtered("codestra_service_intake_id"):
            if not order.codestra_project_id:
                intake = order.codestra_service_intake_id
                project = self.env["project.project"].create({
                    "name": f"{order.name} - {intake.name}",
                    "partner_id": order.partner_id.id,
                    "allow_timesheets": True,
                })
                self.env["project.task"].create({"name":"Discovery and requirements","project_id":project.id})
                self.env["project.task"].create({"name":"Delivery milestone","project_id":project.id})
                order.codestra_project_id = project
                intake.delivery_team_id = project
        return result

class ServiceProposal(models.Model):
    _name = "codestra.service.proposal"; _description = "Service Proposal"; _inherit = "codestra.vertical.mixin"
    intake_id = fields.Many2one("codestra.service.intake", required=True); sale_order_id = fields.Many2one("sale.order")
    scope = fields.Text(required=True); amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", required=True, default=lambda s:s.env.company.currency_id)
    proposal_state = fields.Selection([("draft","Draft"),("sent","Sent"),("approved","Approved"),("rejected","Rejected")], default="draft", required=True)

class ClientSuccessFollowup(models.Model):
    _name = "codestra.client.success.followup"; _description = "Client Success Follow-Up"; _inherit = "codestra.vertical.mixin"
    partner_id = fields.Many2one("res.partner", required=True); project_id = fields.Many2one("project.project")
    followup_at = fields.Datetime(required=True); outcome = fields.Text(); renewal_date = fields.Date()
''',
"senior": r'''
from odoo import fields, models

class SeniorCustomerProfile(models.Model):
    _name = "codestra.senior.profile"; _description = "Senior Customer Protection Profile"; _inherit = "codestra.vertical.mixin"
    partner_id = fields.Many2one("res.partner", required=True); caregiver_id = fields.Many2one("res.partner")
    authorized_representative_id = fields.Many2one("res.partner")
    accessibility_needs = fields.Text(); communication_preference = fields.Selection([("phone","Phone"),("email","Email"),("mail","Mail"),("caregiver","Caregiver")])
    protection_review_state = fields.Selection([("pending","Pending"),("cleared","Cleared"),("hold","Hold")], default="pending", required=True)

class SeniorRecommendation(models.Model):
    _name = "codestra.senior.recommendation"; _description = "Senior Product Recommendation"; _inherit = "codestra.vertical.mixin"
    profile_id = fields.Many2one("codestra.senior.profile", required=True)
    product_id = fields.Many2one("product.product", required=True); reason = fields.Text(required=True)
    needs_assessment = fields.Text(required=True); consent_confirmed = fields.Boolean(required=True)

class SeniorDeliveryFollowup(models.Model):
    _name = "codestra.senior.delivery.followup"; _description = "Senior Delivery and Training Follow-Up"; _inherit = "codestra.vertical.mixin"
    profile_id = fields.Many2one("codestra.senior.profile", required=True); sale_order_id = fields.Many2one("sale.order")
    picking_id = fields.Many2one("stock.picking"); installation_at = fields.Datetime(); training_completed = fields.Boolean()
    complaint = fields.Text(); return_requested = fields.Boolean(); retention_outcome = fields.Text()
''',
}

ANCHORS = {
    "transport": "codestra_transportation_crm",
    "loan": "codestra_loan_origination",
    "student": "codestra_student_repayment",
    "services": "codestra_service_intake",
    "senior": "codestra_senior_products",
}

MODEL_ACCESS = {
    "transport": [
        ("transport_lane","codestra_transport_lane"), ("transport_load","codestra_transport_load"),
        ("transport_quote","codestra_transport_quote"), ("transport_dispatch","codestra_transport_dispatch"),
        ("transport_insurance","codestra_transport_insurance"),
    ],
    "loan": [
        ("borrower_profile","codestra_borrower_profile"), ("loan_application","codestra_loan_application"),
        ("loan_decision_audit","codestra_loan_decision_audit"), ("loan_document","codestra_loan_document"),
        ("loan_payment_schedule","codestra_loan_payment_schedule"), ("loan_collection","codestra_loan_collection"),
    ],
    "student": [
        ("student_case","codestra_student_servicer_case"), ("student_plan","codestra_student_repayment_plan"),
        ("student_document","codestra_student_document_verification"),
    ],
    "services": [
        ("service_intake","codestra_service_intake"), ("service_proposal","codestra_service_proposal"),
        ("client_success","codestra_client_success_followup"),
    ],
    "senior": [
        ("senior_profile","codestra_senior_profile"), ("senior_recommendation","codestra_senior_recommendation"),
        ("senior_delivery","codestra_senior_delivery_followup"),
    ],
}


for domain, modules in GROUPS.items():
    anchor = ANCHORS[domain]
    for i, module in enumerate(modules):
        write(f"{module}/__init__.py", "from . import models\n")
        write(f"{module}/models/__init__.py", "from . import models\n")
        if i == 0:
            deps = ["codestra_vertical_core"] + OFFICIAL[domain]
            data = ["security/ir.model.access.csv", "security/rules.xml", "views/views.xml"]
            write(f"{module}/models/models.py", ANCHOR_MODELS[domain])
            access = ["id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink"]
            for aid, model in MODEL_ACCESS[domain]:
                access.append(f"access_{aid}_agent,{aid} agent,model_{model},codestra_vertical_core.group_vertical_agent,1,1,1,0")
                access.append(f"access_{aid}_admin,{aid} admin,model_{model},call_center_core.group_call_center_admin,1,1,1,1")
            write(f"{module}/security/ir.model.access.csv", "\n".join(access) + "\n")
            rule_records = []
            for aid, model in MODEL_ACCESS[domain]:
                if "audit" in aid:
                    continue
                rule_records.append(f'''  <record id="rule_{aid}_scope" model="ir.rule"><field name="name">{aid} authorized scope</field><field name="model_id" ref="model_{model}"/><field name="groups" eval="[(4, ref('codestra_vertical_core.group_vertical_agent'))]"/><field name="domain_force">[('company_id','in',user.company_ids.ids),('business_unit_id','in',user.call_center_business_unit_ids.ids)]</field></record>''')
            write(f"{module}/security/rules.xml", "<odoo>\n" + "\n".join(rule_records) + "\n</odoo>\n")
            first_model = MODEL_ACCESS[domain][0][1].replace("_", ".")
            write(f"{module}/views/views.xml", f'''
<odoo>
  <record id="view_{domain}_list" model="ir.ui.view"><field name="name">{first_model}.list</field><field name="model">{first_model}</field><field name="arch" type="xml"><list><field name="display_name"/><field name="business_unit_id"/><field name="campaign_id"/><field name="lifecycle_state"/></list></field></record>
  <record id="action_{domain}" model="ir.actions.act_window"><field name="name">{domain.title()}</field><field name="res_model">{first_model}</field><field name="view_mode">list,form</field></record>
  <menuitem id="menu_{domain}" name="{domain.title()}" parent="codestra_vertical_core.menu_codestra_vertical_root" action="action_{domain}" sequence="{10 + list(GROUPS).index(domain)*10}"/>
</odoo>
''')
        else:
            deps = [anchor]
            data = []
            model_name = MODEL_ACCESS[domain][0][1].replace("_", ".")
            field_name = module.removeprefix("codestra_") + "_enabled"
            write(f"{module}/models/models.py", f'''
from odoo import fields, models

class CapabilityExtension(models.Model):
    _inherit = "{model_name}"
    {field_name} = fields.Boolean(default=True, string="{module.replace('_', ' ').title()}")
''')
        write(f"{module}/__manifest__.py", manifest(module, deps, data, i == 0))
        write(f"{module}/tests/__init__.py", "from . import test_install\n")
        expected_model = MODEL_ACCESS[domain][0][1].replace("_", ".")
        write(f"{module}/tests/test_install.py", f'''
from odoo.tests.common import TransactionCase, tagged

@tagged("post_install", "-at_install")
class Test{module.title().replace("_", "")}(TransactionCase):
    def test_capability_model_registered(self):
        self.assertIn("{expected_model}", self.env)
''')

write("README.md", """
# Codestra Odoo 19 Vertical Suite

Codestra-owned modules extending the existing call-center, CRM, campaign, and
business-unit foundation. All integration delivery remains inactive by design.
""")

print(f"Generated {1 + sum(map(len, GROUPS.values()))} Codestra-owned modules in {ROOT}")
