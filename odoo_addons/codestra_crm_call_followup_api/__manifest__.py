{
    "name": "Codestra CRM Call Follow-up API",
    "version": "19.0.1.0.0",
    "summary": "Versioned, replay-safe RPC contract for completed-call ingestion",
    "description": (
        "Adds a strict v1 RPC contract, deterministic request fingerprints, "
        "reconciliation endpoints, and integration capability discovery to "
        "Codestra CRM Call Follow-up."
    ),
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "category": "Sales/CRM",
    "depends": ["codestra_crm_call_followup"],
    "data": [
        "views/call_followup_api_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
