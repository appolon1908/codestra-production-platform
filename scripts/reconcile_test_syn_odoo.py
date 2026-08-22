"""Dry-run-first Odoo-shell reconciliation for the dedicated TEST_SYN fixture.

Execute through the production Odoo shell. Set TEST_SYN_APPLY=YES only after the
protected platform release has been approved. No VICIdial write is performed.
"""

import json
import os


APPLY = os.environ.get("TEST_SYN_APPLY") == "YES"
employee = env["hr.employee"].browse(16).exists()
user = env["res.users"].browse(129).exists()
unit = env["call.center.business.unit"].browse(2).exists()
if not employee or not user or not unit:
    raise RuntimeError("approved TEST_SYN Odoo anchors are missing")

specs = [
    ("keycloak", "46c6027f-1ea8-4010-a104-5b908aabb715", "synthetic.agent.test.syn.6101", {}),  # gitleaks:allow -- public synthetic UUID
    ("vicidial", "cod00016", "cod00016", {}),
    ("sip", "6101", "6101", {"extension": "6101", "endpoint_id": "6101"}),
]
links = env["codestra.identity.link"]
observed = []
for system, external_id, external_username, extra in specs:
    link = links.search([("employee_id", "=", employee.id), ("system", "=", system)], limit=1)
    values = {
        "system": system, "external_id": external_id,
        "external_username": external_username, "employee_id": employee.id,
        "business_unit_id": unit.id, "state": "active", "drift_state": "aligned",
        "is_primary": True, **extra,
    }
    matches = bool(link and all(link[name] == value for name, value in values.items()))
    if APPLY and not matches:
        link.write(values) if link else links.create(values)
    observed.append({"system": system, "before_match": matches})

campaign_model = env["codestra.vicidial.campaign"]
campaign = campaign_model.search([("campaign_id", "=", "TEST_SYN")], limit=1)
campaign_values = {
    "name": "TEST_SYN Synthetic Certification", "campaign_id": "TEST_SYN",
    "campaign_type": "INBOUND", "inbound_group": "TEST_IN", "mode": "test",
    "read_only": True, "sync_enabled": False, "active": True,
}
if APPLY:
    campaign.write(campaign_values) if campaign else campaign_model.create(campaign_values)
    campaign = campaign_model.search([("campaign_id", "=", "TEST_SYN")], limit=1)

agent_model = env["codestra.vicidial.agent"]
agent = agent_model.search(["|", ("vicidial_user", "=", "cod00016"), ("phone_login", "=", "6101")], limit=1)
agent_values = {
    "name": "Synthetic Agent TEST_SYN 6101", "employee_code": "COD.2026.00016",
    "vicidial_user": "cod00016", "phone_login": "6101", "user_group": "WEBTEST_SYN",
    "odoo_user_id": user.id, "campaign_ids": [(6, 0, campaign.ids)] if campaign else [],
    "status": "offline", "sync_state": "synced", "active": True,
    "notes": "Restricted synthetic certification identity; no production dialing authority.",
}
if APPLY:
    agent.write(agent_values) if agent else agent_model.create(agent_values)
    env.cr.commit()
else:
    env.cr.rollback()

print(json.dumps({
    "apply": APPLY, "username": "synthetic.agent.test.syn.6101", "tenant": "COD",
    "campaign": "TEST_SYN", "extension": "6101", "employee_id": "COD.2026.00016",
    "odoo_user_id": user.id, "links": observed,
}, sort_keys=True))
