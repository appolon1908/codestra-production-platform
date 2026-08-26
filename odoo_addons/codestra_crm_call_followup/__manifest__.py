{
    "name": "Codestra CRM Call Follow-up",
    "version": "19.0.1.0.0",
    "summary": "Modern post-call CRM workflow, callback calendar, and appointment reminders",
    "description": (
        "Provides an idempotent post-call popup for agents, structured outcomes "
        "and notes, callback and appointment scheduling, a 30-minute in-app "
        "preparation reminder, and a 15-minute email reminder for the client "
        "and assigned agent."
    ),
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["crm", "calendar", "mail", "bus", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/rules.xml",
        "data/mail_templates.xml",
        "data/calendar_alarm_data.xml",
        "views/post_call_wizard_views.xml",
        "views/call_followup_views.xml",
        "views/crm_lead_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_crm_call_followup/static/src/js/post_call_service.js",
            "codestra_crm_call_followup/static/src/scss/post_call.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
