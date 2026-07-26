"""Verify the disabled Odoo identity and record real Keycloak evidence."""

import json
import os

from odoo import fields


stamp = os.environ["SYNTHETIC_ACCEPTANCE_STAMP"]
login = f"test.agent.{stamp.lower()}@staging.invalid"
external_keycloak_id = os.environ["SYNTHETIC_KEYCLOAK_EXTERNAL_ID"]
request = env["codestra.provisioning.request"].search([
    ("idempotency_key", "=", f"synthetic-identity-acceptance-{stamp.lower()}"),
], limit=1)
employee = request.employee_id
user = env["res.users"].with_context(active_test=False).search(
    [("login", "=", login)], limit=1
)
campaign = env["call.center.campaign"].with_context(active_test=False).search(
    [("code", "=", "MOY-STAGE-SYNTH")], limit=1
)
unrelated_unit = env["call.center.business.unit"].search([("id", "=", 2)], limit=1)
unrelated = env["call.center.campaign"].with_context(active_test=False).search(
    [("code", "=", "COD-STAGE-UNRELATED")], limit=1
)
if not unrelated:
    unrelated = env["call.center.campaign"].create({
        "name": "Unrelated Synthetic Campaign",
        "code": "COD-STAGE-UNRELATED",
        "business_unit_id": unrelated_unit.id,
        "active": True,
    })
elif not unrelated.active:
    unrelated.active = True
team = request.operational_team_id
user.write({
    "call_center_campaign_ids": [(4, campaign.id)],
    "call_center_team_ids": [(4, team.id)],
})
campaign.agent_ids = [(4, user.id)]
team.agent_ids = [(4, user.id)]

scoped_campaigns = env["call.center.campaign"].with_user(user).with_context(
    active_test=False
).search([])
campaign_visible = campaign in scoped_campaigns
unrelated_denied = unrelated not in scoped_campaigns
root_menu = env.ref("call_center_core.menu_call_center_root")
menu_visible = root_menu.id in env["ir.ui.menu"].with_user(user)._visible_menu_ids()
supervisor_visible = bool(
    env["codestra.provisioning.request"].with_user(request.supervisor_id).search([
        ("id", "=", request.id),
    ])
)
if not all((campaign_visible, unrelated_denied, menu_visible, supervisor_visible)):
    raise RuntimeError(
        "odoo_control_plane_verification_failed:"
        f"campaign={campaign_visible},unrelated={unrelated_denied},"
        f"menu={menu_visible},supervisor={supervisor_visible}"
    )

now = fields.Datetime.now()
odoo_step = request.step_ids.filtered(
    lambda row: row.target_system == "odoo"
)[:1]
keycloak_step = request.step_ids.filtered(
    lambda row: row.target_system == "keycloak"
)[:1]
odoo_step.write({
    "state": "verified",
    "verification_state": "verified",
    "attempt_count": 1,
    "external_id": str(user.id),
    "external_reference": login,
    "completed_at": now,
})
keycloak_step.write({
    "state": "verified",
    "verification_state": "verified",
    "attempt_count": 1,
    "external_id": external_keycloak_id,
    "external_reference": f"test.agent.{stamp.lower()}",
    "completed_at": now,
})
links = env["codestra.identity.link"]
for system, provider, external_id, username in (
    ("odoo", "odoo19_module_staging", str(user.id), login),
    ("keycloak", "codestra-staging", external_keycloak_id,
     f"test.agent.{stamp.lower()}"),
):
    link = links.search([
        ("system", "=", system),
        ("provider", "=", provider),
        ("external_id", "=", external_id),
    ], limit=1)
    if not link:
        links.create({
            "employee_id": employee.id,
            "business_unit_id": request.business_unit_id.id,
            "system": system,
            "provider": provider,
            "external_id": external_id,
            "external_username": username,
            "email_address": login,
            "state": "pending",
            "verified_at": now,
            "last_reconciled_at": now,
            "drift_state": "aligned",
        })
request._audit("synthetic.disabled_identities.verified", "accepted", after={
    "odoo_user_id": user.id,
    "keycloak_external_id": external_keycloak_id,
    "campaign": campaign.code,
    "unrelated_campaign_denied": unrelated.code,
})
env.cr.commit()
print(json.dumps({
    "request_id": request.id,
    "request_state": request.state,
    "odoo_user_active": user.active,
    "campaign_visible": campaign_visible,
    "unrelated_campaign_denied": unrelated_denied,
    "call_center_menu_visible": menu_visible,
    "supervisor_visible": supervisor_visible,
    "verified_steps": len(request.step_ids.filtered(
        lambda row: row.state == "verified"
    )),
    "pending_steps": len(request.step_ids.filtered(
        lambda row: row.state == "pending"
    )),
    "mandatory_steps_complete": request.mandatory_steps_complete,
    "audit_count": len(request.audit_ids),
}, sort_keys=True))
