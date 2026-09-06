{
    "name": "Codestra CRM Call Follow-up Automation",
    "version": "19.0.1.0.0",
    "summary": "Durable middleware outbox for post-call CRM automation",
    "description": (
        "Captures post-call and scheduling events in a transactional Odoo outbox "
        "and delivers them asynchronously to the approved Codestra middleware."
    ),
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "data/ir_cron_data.xml",
        "views/outbox_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
