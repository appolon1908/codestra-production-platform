"""Create and verify one disabled Keycloak staging identity.

Run inside the private provisioning-service container. The script never
activates the identity and never handles a user password.
"""

import asyncio
import json
import os
from datetime import UTC, datetime

from app.adapters import load_adapters
from app.contracts import Operation, StepCommand, TargetSystem
from app.keycloak import REQUIRED_ACTIONS
from app.repository import StateRepository


stamp = os.environ["SYNTHETIC_ACCEPTANCE_STAMP"]
employee_number = os.environ["SYNTHETIC_EMPLOYEE_NUMBER"]
username = f"test.agent.{stamp.lower()}"
base_key = f"synthetic-keycloak-{stamp.lower()}"
payload = {
    "username": username,
    "email": f"{username}@staging.invalid",
    "first_name": "Test",
    "last_name": "Agent",
    "attributes": {
        "employee_id": employee_number,
        "company_id": "1",
        "business_unit_id": "1",
        "department_id": "transportation-staging-identity-acceptance",
        "team_id": "transportation-staging-agents",
        "supervisor_id": "odoo-user-6",
        "campaign_ids": ["MOY-STAGE-SYNTH"],
        "role_template": "AGENT",
        "agent_desktop_roles": ["agent"],
    },
    "groups": ["/provisioning-staging/teams/keycloak-acceptance"],
    "realm_roles": ["codestra_agent"],
    "client_roles": {"codestra-agent-desktop": ["agent"]},
}


def command(operation):
    return StepCommand(
        schema_version="1.0",
        request_id="PRV-2026-000040",
        correlation_id="1994c1c6-0069-4dd5-90f2-4b8d43b9b46e",
        idempotency_key=base_key,
        employee_id=employee_number,
        target_system=TargetSystem.KEYCLOAK,
        operation=operation,
        timestamp=datetime.now(UTC),
        step_id=f"keycloak-{stamp.lower()}-{operation.value}",
        sequence=20,
        payload=payload,
    )


async def main():
    repository = StateRepository(os.environ["STATE_DATABASE_PATH"])
    adapter = load_adapters(
        os.environ["ADAPTER_CONFIG_FILE"],
        repository,
        os.environ["CREDENTIAL_ENCRYPTION_KEY_FILE"],
    )["keycloak"]
    created = await adapter.create_disabled(command(Operation.CREATE_DISABLED))
    replay = await adapter.create_disabled(command(Operation.CREATE_DISABLED))
    await adapter.update(command(Operation.UPDATE))
    verified = await adapter.verify(command(Operation.VERIFY))
    user = await adapter._user_for_command(command(Operation.VERIFY))
    snapshot = await adapter._snapshot(user)
    checks = {
        "disabled": user["enabled"] is False,
        "password_setup_required": "UPDATE_PASSWORD" in user["requiredActions"],
        "mfa_enrollment_required": "CONFIGURE_TOTP" in user["requiredActions"],
        "group_assigned": (
            "/provisioning-staging/teams/keycloak-acceptance"
            in snapshot["groups"]
        ),
        "realm_role_assigned": "codestra_agent" in snapshot["realm_roles"],
        "desktop_role_assigned": (
            "agent" in snapshot["client_roles"].get("codestra-agent-desktop", [])
        ),
        "campaign_attribute_assigned": (
            snapshot["attributes"].get("campaign_ids") == ["MOY-STAGE-SYNTH"]
        ),
        "idempotent_replay": replay["external_id"] == created["external_id"],
        "verified": verified["state"] == "verified",
    }
    if not all(checks.values()):
        raise RuntimeError("keycloak_disabled_identity_verification_failed")
    print(json.dumps({
        "checks": checks,
        "employee_number": employee_number,
        "external_id": created["external_id"],
        "username": username,
        "state": "disabled_verified",
        "required_actions": sorted(REQUIRED_ACTIONS),
    }, sort_keys=True))


asyncio.run(main())
