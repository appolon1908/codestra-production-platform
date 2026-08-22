"""Dry-run-first Odoo-shell reconciliation for the dedicated TEST_SYN fixture.

Execute through the production Odoo shell. Set TEST_SYN_APPLY=YES only after the
protected platform release has been approved. No VICIdial write is performed.
"""

import json
import os


APPLY = os.environ.get("TEST_SYN_APPLY") == "YES"


def field_matches(record, name, expected):
    """Compare scalar and many2one fields without recordset/int ambiguity."""
    actual = record[name]
    if isinstance(expected, int) and hasattr(actual, "id"):
        return actual.id == expected
    return actual == expected


unit = env["call.center.business.unit"].search([("code", "=", "COD")], limit=1)
if not unit:
    raise RuntimeError("authoritative COD business unit is missing")
user = env["res.users"].with_context(active_test=False).search([
    ("login", "=", "synthetic.agent.test.syn.6101")
], limit=1)
employee = env["hr.employee"].with_context(active_test=False).search([
    ("codestra_employee_number", "=", "COD.2026.00016")
], limit=1)
if APPLY and not user:
    user = env["res.users"].create({
        "name": "Synthetic Agent 6101", "login": "synthetic.agent.test.syn.6101",
        "email": "synthetic.agent.test.syn.6101@invalid.example", "active": True,
        "company_id": env.company.id, "company_ids": [(6, 0, [env.company.id])],
    })
if APPLY and not employee:
    employee = env["hr.employee"].create({
        "name": "Synthetic Agent 6101", "codestra_employee_number": "COD.2026.00016",
        "work_email": "synthetic.agent.test.syn.6101@invalid.example",
        "user_id": user.id, "active": True,
    })
if APPLY and not user.active:
    user.write({"active": True})
if APPLY and not employee.active:
    employee.write({"active": True})
if APPLY and (not employee.user_id or employee.user_id != user):
    employee.write({"user_id": user.id})
if not employee or not user:
    env.cr.rollback()
    print(json.dumps({"apply": APPLY, "status": "DRIFT", "reason": "TEST_SYN Odoo user or employee missing"}, sort_keys=True))
    raise SystemExit(0)

specs = [
    ("keycloak", "46c6027f-1ea8-4010-a104-5b908aabb715", "synthetic.agent.test.syn.6101", {}),  # gitleaks:allow -- public synthetic UUID
    ("vicidial", "cod00016", "cod00016", {}),
    ("sip", "6101", "6101", {"extension": "6101", "endpoint_id": "6101"}),
]
links = env["codestra.identity.link"]
observed = []
desired_links = []
for system, external_id, external_username, extra in specs:
    link = links.search([("employee_id", "=", employee.id), ("system", "=", system)], limit=1)
    values = {
        "system": system, "external_id": external_id,
        "external_username": external_username, "employee_id": employee.id,
        "business_unit_id": unit.id, "state": "active", "drift_state": "aligned",
        "is_primary": True, **extra,
    }
    matches = bool(link and all(field_matches(link, name, value) for name, value in values.items()))
    if APPLY and not matches:
        link.write(values) if link else links.create(values)
    observed.append({"system": system, "before_match": matches})
    desired_links.append((system, values))

campaign_model = env["codestra.vicidial.campaign"]
campaign = campaign_model.with_context(active_test=False).search([
    ("campaign_id", "=", "TEST_SYN")
], limit=1)
campaign_values = {
    "name": "TEST_SYN Synthetic Certification", "campaign_id": "TEST_SYN",
    "campaign_type": "INBOUND", "inbound_group": "TEST_IN", "mode": "test",
    "read_only": True, "sync_enabled": False, "active": True,
}
if APPLY:
    campaign.write(campaign_values) if campaign else campaign_model.create(campaign_values)
    campaign = campaign_model.search([("campaign_id", "=", "TEST_SYN")], limit=1)

agent_model = env["codestra.vicidial.agent"]
agent = agent_model.with_context(active_test=False).search([
    "|", ("vicidial_user", "=", "cod00016"), ("phone_login", "=", "6101")
], limit=1)
agent_values = {
    "name": "Synthetic Agent TEST_SYN 6101", "employee_code": "COD.2026.00016",
    "vicidial_user": "cod00016", "phone_login": "6101", "user_group": "WEBTEST_SYN",
    "odoo_user_id": user.id, "campaign_ids": [(6, 0, campaign.ids)] if campaign else [],
    "status": "offline", "sync_state": "synced", "active": True,
    "notes": "Restricted synthetic certification identity; no production dialing authority.",
}
if APPLY:
    agent.write(agent_values) if agent else agent_model.create(agent_values)

user.invalidate_recordset(["active"])
employee.invalidate_recordset(["active", "user_id"])
anchor_match = bool(user.active and employee.active and employee.user_id == user)
link_readback = []
for system, values in desired_links:
    link = links.search([
        ("employee_id", "=", employee.id), ("system", "=", system)
    ], limit=1)
    matches = bool(link and all(field_matches(link, name, value) for name, value in values.items()))
    link_readback.append({"system": system, "match": matches})

campaign = campaign_model.with_context(active_test=False).search([
    ("campaign_id", "=", "TEST_SYN")
], limit=1)
campaign_match = bool(campaign and all(
    field_matches(campaign, name, value) for name, value in campaign_values.items()
))
agent = agent_model.with_context(active_test=False).search([
    "|", ("vicidial_user", "=", "cod00016"), ("phone_login", "=", "6101")
], limit=1)
agent_scalar_values = {
    name: value for name, value in agent_values.items() if name != "campaign_ids"
}
agent_match = bool(
    agent
    and all(field_matches(agent, name, value) for name, value in agent_scalar_values.items())
    and set(agent.campaign_ids.ids) == set(campaign.ids)
)
complete_match = bool(
    anchor_match and all(item["match"] for item in link_readback)
    and campaign_match and agent_match
)
if APPLY and not complete_match:
    env.cr.rollback()
    raise RuntimeError("TEST_SYN Odoo fixture failed complete post-write readback")
if APPLY:
    env.cr.commit()
else:
    env.cr.rollback()

print(json.dumps({
    "apply": APPLY, "username": "synthetic.agent.test.syn.6101", "tenant": "COD",
    "campaign": "TEST_SYN", "extension": "6101", "employee_id": "COD.2026.00016",
    "odoo_user_id": user.id, "odoo_employee_id": employee.id,
    "links_before": observed, "links_readback": link_readback,
    "anchor_match": anchor_match, "campaign_match": campaign_match,
    "agent_match": agent_match, "status": "PASS" if complete_match else "DRIFT",
}, sort_keys=True))
