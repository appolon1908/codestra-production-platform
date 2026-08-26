{
    "name": "Codestra CRM Call Follow-up Automation",
    "version": "19.0.1.0.0",
    "summary": "Durable SLA, missed-callback, and reminder-health automation",
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup", "crm", "calendar", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "data/cron.xml",
        "views/automation_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
