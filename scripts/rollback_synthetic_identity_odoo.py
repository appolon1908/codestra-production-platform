"""Fail closed and roll back the partially provisioned synthetic identity."""

import json
import os

from odoo import fields


stamp = os.environ["SYNTHETIC_ACCEPTANCE_STAMP"]
extension = os.environ.get("SYNTHETIC_SIP_EXTENSION", "6199")
request = env["codestra.provisioning.request"].search([
    ("idempotency_key", "=", f"synthetic-identity-acceptance-{stamp.lower()}"),
], limit=1)
if not request:
    raise RuntimeError("synthetic_request_not_found")
now = fields.Datetime.now()
for step in request.step_ids.filtered(lambda row: row.state == "pending"):
    step.write({
        "state": "blocked",
        "verification_state": "unknown",
        "last_error_code": "STAGING_ADAPTER_NOT_CONFIGURED",
        "last_error_sanitized": (
            "The required private staging adapter was not configured; "
            "activation was denied."
        ),
        "completed_at": now,
    })
request.state = "partially_provisioned"
request._audit("synthetic.activation.denied", "blocked", after={
    "reason": "mandatory_staging_adapters_unavailable",
    "blocked_systems": request.step_ids.filtered(
        lambda row: row.state == "blocked"
    ).mapped("target_system"),
})
request.step_ids.filtered(
    lambda row: row.target_system in ("odoo", "keycloak")
).write({
    "compensation_state": "completed",
})
request.employee_id.user_id.active = False
request.employee_id.provisioning_state = "terminated"
request.employee_id.active = False
request.employment_status = "terminated"
request.env["codestra.identity.link"].search([
    ("employee_id", "=", request.employee_id.id),
]).write({
    "state": "terminated",
    "terminated_at": now,
    "last_reconciled_at": now,
    "drift_state": "aligned",
})
assignments = request.env["codestra.extension.assignment"].search([
    ("request_id", "=", request.id),
    ("state", "in", ("reserved", "committed")),
])
assignments.write({
    "state": "released",
    "released_at": now,
})
reservations = request.env["codestra.identifier.reservation"].search([
    ("request_id", "=", request.id),
    ("state", "=", "reserved"),
])
reservations.write({
    "state": "released",
    "released_at": now,
})
request.env["codestra.extension.pool"].search([
    ("code", "=", f"MOY-STAGE-{extension}"),
]).active = False
request.env["call.center.campaign"].with_context(active_test=False).search([
    ("code", "in", ("MOY-STAGE-SYNTH", "COD-STAGE-UNRELATED")),
]).active = False
request.state = "terminated"
request._audit("synthetic.rollback.completed", "accepted", after={
    "odoo_user_active": False,
    "extension_released": assignments.mapped("extension"),
    "identifiers_released": reservations.mapped("identifier_type"),
    "historical_records_preserved": True,
})
env.cr.commit()
print(json.dumps({
    "request_id": request.id,
    "request_state": request.state,
    "employee_active": request.employee_id.active,
    "odoo_user_active": request.employee_id.user_id.active,
    "blocked_steps": len(request.step_ids.filtered(
        lambda row: row.state == "blocked"
    )),
    "compensated_steps": len(request.step_ids.filtered(
        lambda row: row.compensation_state == "completed"
    )),
    "released_assignments": assignments.mapped("extension"),
    "released_identifiers": reservations.mapped("identifier_type"),
    "identity_link_states": request.env["codestra.identity.link"].search([
        ("employee_id", "=", request.employee_id.id),
    ]).mapped("state"),
    "audit_count": len(request.audit_ids),
}, sort_keys=True))
