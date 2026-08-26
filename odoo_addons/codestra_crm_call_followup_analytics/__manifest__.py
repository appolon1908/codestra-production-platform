{
    "name": "Codestra CRM Call Follow-up Supervisor Analytics",
    "version": "19.0.1.0.0",
    "summary": "Read-only post-call SLA, outcome, compliance, and workload reporting",
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "views/call_followup_report_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
