"""Run with `odoo shell` against the isolated module-staging database.

Creates only a disabled synthetic identity. External activation is deliberately
outside this script and the provisioning request remains non-active.
"""

import json
import os

from odoo import fields


stamp = os.environ["SYNTHETIC_ACCEPTANCE_STAMP"]
extension = int(os.environ.get("SYNTHETIC_SIP_EXTENSION", "6199"))
if not 6100 <= extension <= 6199 or extension == 6101:
    raise RuntimeError("synthetic SIP extension is outside the approved staging range")
login = f"synthetic.agent.{stamp.lower()}@staging.invalid"
idempotency = f"synthetic-identity-acceptance-{stamp.lower()}"

unit = env["call.center.business.unit"].search([("id", "=", 1)], limit=1)
company = unit.company_id or env.company
supervisor = env.ref("base.user_demo")
supervisor.write({
    "call_center_business_unit_ids": [(4, unit.id)],
    "call_center_default_business_unit_id": unit.id,
    "group_ids": [
        (4, env.ref(
            "codestra_identity_provisioning.group_provisioning_approver"
        ).id),
        (4, env.ref("call_center_core.group_call_center_supervisor").id),
    ],
})
department = env["call.center.department"].search(
    [("code", "=", "MOY-STAGE-ID"), ("business_unit_id", "=", unit.id)], limit=1
)
if not department:
    department = env["call.center.department"].create({
        "name": "Transportation Staging Identity Acceptance",
        "code": "MOY-STAGE-ID",
        "business_unit_id": unit.id,
        "manager_id": supervisor.id,
        "member_ids": [(6, 0, supervisor.ids)],
    })
team = env["call.center.team"].search(
    [("code", "=", "MOY-STAGE-AGENT"), ("business_unit_id", "=", unit.id)], limit=1
)
if not team:
    team = env["call.center.team"].create({
        "name": "Transportation Staging Agents",
        "code": "MOY-STAGE-AGENT",
        "business_unit_id": unit.id,
        "department_id": department.id,
        "manager_id": supervisor.id,
        "supervisor_ids": [(6, 0, supervisor.ids)],
        "capacity": 2,
    })
campaign = env["call.center.campaign"].with_context(active_test=False).search(
    [("code", "=", "MOY-STAGE-SYNTH"), ("business_unit_id", "=", unit.id)], limit=1
)
if not campaign:
    campaign = env["call.center.campaign"].create({
        "name": "Transportation Synthetic Identity Acceptance",
        "code": "MOY-STAGE-SYNTH",
        "business_unit_id": unit.id,
        "active": True,
    })
elif not campaign.active:
    campaign.active = True
inbound = env["codestra.provisioning.inbound.group"].search(
    [("code", "=", "TEST_IN"), ("business_unit_id", "=", unit.id)], limit=1
)
if not inbound:
    inbound = env["codestra.provisioning.inbound.group"].create({
        "name": "Codestra Test Inbound",
        "code": "TEST_IN",
        "external_reference": "TEST_IN",
        "business_unit_id": unit.id,
    })
role = env["codestra.role.template"].search(
    [("code", "=", "AGENT"), ("business_unit_id", "=", unit.id),
     ("active", "=", True)],
    order="version desc,id desc", limit=1,
)
employee = env["hr.employee"].search(
    [("name", "=", f"Synthetic Agent {stamp}")], limit=1
)
if not employee:
    employee = env["hr.employee"].create({
        "name": f"Synthetic Agent {stamp}",
        "company_id": company.id,
        "department_id": False,
        "work_email": login,
        "provisioning_state": "pending",
    })
user = env["res.users"].with_context(active_test=False).search(
    [("login", "=", login)], limit=1
)
if not user:
    agent_group = env.ref("call_center_core.group_call_center_agent")
    user = env["res.users"].with_context(no_reset_password=True).create({
        "name": f"Synthetic Agent {stamp}",
        "login": login,
        "email": login,
        "active": False,
        "company_id": company.id,
        "company_ids": [(6, 0, company.ids)],
        "group_ids": [(6, 0, (env.ref("base.group_user") | agent_group).ids)],
        "call_center_business_unit_ids": [(6, 0, unit.ids)],
        "call_center_default_business_unit_id": unit.id,
    })
employee.user_id = user
request = env["codestra.provisioning.request"].create({
    "request_type": "onboard",
    "employee_id": employee.id,
    "personal_email": login,
    "requested_by": supervisor.id,
    "supervisor_id": supervisor.id,
    "approval_owner_id": supervisor.id,
    "company_id": company.id,
    "business_unit_id": unit.id,
    "department_id": department.id,
    "operational_team_id": team.id,
    "role_template_id": role.id,
    "campaign_ids": [(6, 0, campaign.ids)],
    "inbound_group_ids": [(6, 0, inbound.ids)],
    "start_date": fields.Date.today(),
    "employment_status": "pending",
    "timezone": "America/Santo_Domingo",
    "needs_company_email": True,
    "needs_sip_endpoint": True,
    "needs_agent_desktop": True,
    "needs_keycloak": True,
    "needs_vicidial": True,
    "operational_approved": True,
    "it_approved": True,
    "idempotency_key": idempotency,
})
if request.campaign_ids != campaign:
    request.campaign_ids = campaign
if request.state == "draft":
    request.action_submit()
if request.state == "pending_approval":
    request.action_approve()
if request.state == "approved":
    request.action_reserve_identifiers()
pool_code = f"MOY-STAGE-{extension}"
pool = env["codestra.extension.pool"].search([("code", "=", pool_code)], limit=1)
if not pool:
    pool = env["codestra.extension.pool"].create({
        "name": f"Transportation Verified Staging {extension}",
        "code": pool_code,
        "business_unit_id": unit.id,
        "start_extension": extension,
        "end_extension": extension,
        "technology": "pjsip",
        "context": "codestra-echo-only",
        "wss_server": "wss://vicidial-staging.codestra.agency:8089/ws",
        "default_expiration_seconds": 3600,
        "active": True,
    })
assignment = env["codestra.extension.assignment"].search(
    [("request_id", "=", request.id), ("extension", "=", str(extension))], limit=1
)
if not assignment:
    assignment = pool.reserve_extension(employee, request)
if not env["codestra.identifier.reservation"].search_count([
    ("request_id", "=", request.id),
    ("identifier_type", "=", "sip_extension"),
]):
    env["codestra.identifier.reservation"].create({
        "identifier_type": "sip_extension",
        "normalized_value": assignment.extension,
        "request_id": request.id,
    })
env.cr.commit()
print(json.dumps({
    "request_id": request.id,
    "request_number": request.request_number,
    "request_state": request.state,
    "correlation_id": request.correlation_id,
    "idempotency_key": request.idempotency_key,
    "employee_id": employee.id,
    "employee_number": employee.codestra_employee_number,
    "odoo_user_id": user.id,
    "odoo_user_active": user.active,
    "login": login,
    "business_unit": unit.name,
    "campaign": campaign.code,
    "inbound_group": inbound.code,
    "role_template": role.code,
    "extension": assignment.extension,
    "step_count": len(request.step_ids),
    "mandatory_steps_complete": request.mandatory_steps_complete,
}, sort_keys=True))
