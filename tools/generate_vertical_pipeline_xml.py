#!/usr/bin/env python3
"""Generate deterministic campaign-vertical CRM stages and transitions."""
from pathlib import Path
from xml.sax.saxutils import escape

pipelines = {
    "transportation": ["New Lead", "Contacted", "Qualification", "Lane and Freight Review", "Rate Preparation", "Quote Sent", "Negotiation", "Carrier/Compliance Review", "Won", "Lost"],
    "moneybee": ["New Application", "Contacted", "Application Started", "Documents Pending", "Underwriting", "Conditional Approval", "Approved", "Declined", "Funded/Completed"],
    "student": ["New Case", "Contacted", "Servicer Verification", "Needs Assessment", "Documents Pending", "Repayment Plan Review", "Assistance Submitted", "Follow-Up", "Resolved", "Closed"],
    "services": ["New Inquiry", "Discovery", "Scope", "Proposal", "Negotiation", "Contract", "Project Handoff", "Delivery", "Won", "Lost"],
    "senior": ["New Inquiry", "First Contact", "Needs Assessment", "Product Recommended", "Follow-Up Required", "Order Preparation", "Payment/Approval", "Won", "Lost"],
}
lines = ['<?xml version="1.0" encoding="utf-8"?>', '<odoo noupdate="1">']
for vertical, stages in pipelines.items():
    # Reverse creation order lets every transition reference an already-created
    # next stage while keeping the XML records noupdate/configurable afterward.
    for index in reversed(range(len(stages))):
        name = stages[index]
        xmlid = f"stage_{vertical}_{index:02d}"
        lines += [
            f'  <record id="{xmlid}" model="crm.stage">',
            f'    <field name="name">{escape(name)}</field>',
            f'    <field name="sequence">{(index + 1) * 10}</field>',
            f'    <field name="codestra_vertical">{vertical}</field>',
        ]
        if index < len(stages) - 1:
            lines.append(
                f'    <field name="allowed_next_stage_ids" '
                f'eval="[(6, 0, [ref(\'stage_{vertical}_{index + 1:02d}\')])]"/>'
            )
        lines.append('  </record>')
lines.append("</odoo>")
Path("/opt/codestra/odoo19-vertical-addons/codestra_vertical_core/data/pipeline_stages.xml").write_text(
    "\n".join(lines) + "\n", encoding="utf-8"
)
