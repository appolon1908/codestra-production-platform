{
    "name": "Codestra CRM Call Follow-up Workspace",
    "version": "19.0.1.0.0",
    "summary": "Modern agent workspace, forms, and safe post-call calls to action",
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup", "crm", "calendar", "mail", "web"],
    "data": [
        "views/workspace_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_crm_call_followup_ux/static/src/scss/workspace.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
