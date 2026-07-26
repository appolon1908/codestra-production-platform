"""Terminate and reconcile the synthetic Keycloak identity."""

import asyncio
import json
import os
from datetime import UTC, datetime

from app.adapters import load_adapters
from app.contracts import Operation, StepCommand, TargetSystem
from app.repository import StateRepository


stamp = os.environ["SYNTHETIC_ACCEPTANCE_STAMP"]
employee_number = os.environ["SYNTHETIC_EMPLOYEE_NUMBER"]
username = f"test.agent.{stamp.lower()}"
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
        idempotency_key=f"synthetic-keycloak-{stamp.lower()}",
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
    result = await adapter.terminate(command(Operation.TERMINATE))
    user = await adapter._user_for_command(command(Operation.VERIFY))
    checks = {
        "disabled": user["enabled"] is False,
        "lifecycle_terminated": (
            user.get("attributes", {}).get("lifecycle_state") == ["terminated"]
        ),
    }
    if not all(checks.values()):
        raise RuntimeError("keycloak_termination_verification_failed")
    print(json.dumps({
        "checks": checks,
        "external_id": user["id"],
        "result_state": result["state"],
        "username": username,
    }, sort_keys=True))


asyncio.run(main())
