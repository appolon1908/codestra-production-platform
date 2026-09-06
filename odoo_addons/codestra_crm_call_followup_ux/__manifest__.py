{
    "name": "Codestra CRM Call Follow-up UX",
    "version": "19.0.1.0.0",
    "summary": "Snooze, contextual actions, and resilient post-call popup recovery",
    "description": (
        "Adds agent snooze controls, contextual completion actions, CRM shortcuts, "
        "and resilient same-session popup recovery to Codestra CRM Call Follow-up."
    ),
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup"],
    "data": [
        "data/ir_cron_data.xml",
        "views/call_followup_views.xml",
        "views/post_call_wizard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_crm_call_followup_ux/static/src/js/post_call_service.js",
            "codestra_crm_call_followup_ux/static/src/scss/post_call_ux.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
