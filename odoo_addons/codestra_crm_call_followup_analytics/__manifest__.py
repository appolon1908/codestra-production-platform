{
    "name": "Codestra CRM Call Follow-up Analytics",
    "version": "19.0.1.0.0",
    "summary": "Read-only operational KPIs for post-call outcomes and callbacks",
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup", "crm", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "views/analytics_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
