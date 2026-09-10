{
    "name": "Codestra CRM Call Follow-up Realtime Leases",
    "version": "19.0.1.0.0",
    "summary": "Cross-tab popup ownership, renewal, and stale-lease recovery",
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup", "web", "bus"],
    "assets": {
        "web.assets_backend": [
            "codestra_crm_call_followup_realtime/static/src/js/post_call_lease_service.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
