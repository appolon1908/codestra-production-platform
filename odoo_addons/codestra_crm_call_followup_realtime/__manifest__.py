{
    "name": "Codestra CRM Call Follow-up Realtime",
    "version": "19.0.1.0.0",
    "summary": "Claimed, recoverable, multi-tab-safe post-call popup delivery",
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup", "bus", "web", "mail"],
    "data": [
        "data/cron.xml",
        "views/realtime_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_crm_call_followup_realtime/static/src/js/post_call_realtime_service.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
