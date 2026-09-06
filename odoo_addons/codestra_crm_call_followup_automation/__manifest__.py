{
    "name": "Codestra CRM Call Follow-up Automation",
    "version": "19.0.1.0.0",
    "summary": "Durable outbox plus SLA and missed-callback automation",
    "description": (
        "Captures post-call and scheduling events in a transactional Odoo outbox "
        "and delivers them asynchronously to the approved Codestra middleware."
    ),
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup", "calendar", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "security/sla_ir.model.access.csv",
        "security/sla_rules.xml",
        "data/ir_cron_data.xml",
        "data/cron.xml",
        "views/outbox_views.xml",
        "views/automation_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
