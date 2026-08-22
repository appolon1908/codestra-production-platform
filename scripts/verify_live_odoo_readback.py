"""Run with Odoo shell to read back synthetic bridge records through the ORM."""

from __future__ import annotations

import json
import os


tag = os.environ["ODOO_SYNTHETIC_TAG"]
correlations = {
    os.environ["ODOO_BRIDGE_CORRELATION"],
    os.environ["ODOO_OUTBOUND_CORRELATION"],
}
partner = env["res.partner"].search([
    ("codestra_integration_external_id", "=", tag),
    ("name", "=", tag),
])
requests = env["codestra.middleware.request"].search([
    ("correlation_id", "=", os.environ["ODOO_BRIDGE_CORRELATION"]),
    ("tenant_id", "=", "codestra-production"),
])
events = env["codestra.integration.event"].search([
    ("correlation_id", "in", list(correlations)),
])
audits = env["codestra.integration.audit"].search([
    ("event_id", "in", events.ids),
])
activities = env["mail.activity"].search([
    ("res_model", "=", "res.partner"),
    ("res_id", "in", partner.ids),
    ("summary", "like", tag),
])
service_id = int(env["ir.config_parameter"].sudo().get_param(
    "codestra.middleware.service_user_id", "0"
))
service = env["res.users"].sudo().browse(service_id).exists()
group = env.ref("codestra_middleware_bridge.group_codestra_middleware_bridge")
assert len(partner) == 1
assert partner.codestra_integration_status == "inactive"
assert len(requests) == 5
assert len(activities) == 1
assert len(events) >= 6 and len(audits) >= 6
assert service and service.active and group in service.group_ids
assert service.login == "codestra.middleware@service.internal"
print(json.dumps({
    "partner_count": len(partner), "request_count": len(requests),
    "activity_count": len(activities), "event_count": len(events),
    "audit_count": len(audits), "tenant_ids": sorted(set(requests.mapped("tenant_id"))),
    "service_user_id": service.id, "service_identity": service.login,
    "status": partner.codestra_integration_status,
}, sort_keys=True))
