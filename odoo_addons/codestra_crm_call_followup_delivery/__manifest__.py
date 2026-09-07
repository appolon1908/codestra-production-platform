{
    "name": "Codestra CRM Call Follow-up Delivery Outbox",
    "version": "19.0.1.0.0",
    "summary": "Auditable email delivery state, retries, and dead-letter operations",
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "data/ir_cron_data.xml",
        "views/delivery_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
