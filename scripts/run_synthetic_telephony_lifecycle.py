#!/usr/bin/env python3
"""Bounded runtime VICIdial/PJSIP lifecycle for one synthetic identity.

Run on the VICIdial staging host. Credentials are read only from protected
files. No credential value is printed or written to the evidence database.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from codestra_edge.provisioning.backend import (
    LiveBackend,
    ManagedPjsipStore,
    NonAgentApi,
)
from codestra_edge.provisioning.service import Principal, ProvisioningService


def credential(path: Path) -> tuple[str, str]:
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw.partition("=")
        if separator:
            values[key] = value
    user = values.get("VICIDIAL_API_USER")
    password = values.get("VICIDIAL_API_PASSWORD")
    if not user or not password:
        raise RuntimeError("protected API credential is incomplete")
    return user, password


def build(args):
    user, password = credential(args.credential_file)
    backend = LiveBackend(
        NonAgentApi(args.api_url, user, password),
        ManagedPjsipStore(
            "/var/lib/codestra-telephony-provisioning/endpoints",
            "/etc/asterisk/codestra-provisioned.d",
            {"codestra-echo-only"},
        ),
        ("mysql", "--batch", "--raw", "--skip-column-names", "asterisk"),
        ("mysql", "--batch", "--raw", "--skip-column-names", "asterisk"),
    )
    service = ProvisioningService(
        backend,
        args.state_file,
        "odoo-provisioning@65.109.65.169",
        writes_enabled=True,
    )
    principal = Principal(
        "odoo-provisioning@65.109.65.169",
        frozenset({"telephony:provision"}),
    )
    return backend, service, principal


def execute(service, principal, operation, key, payload):
    return service.execute(
        principal, operation, f"{key}-{operation}", payload
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=("provision", "suspend", "reactivate", "terminate", "reconcile"),
    )
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--agent-password-file", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--employee-id", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--extension", type=int, required=True)
    args = parser.parse_args()
    if not 6100 <= args.extension <= 6199 or args.extension == 6101:
        raise RuntimeError("extension is outside the approved staging range")
    backend, service, principal = build(args)
    base = {
        "employee_id": args.employee_id,
        "username": args.username,
        "full_name": "Test Agent Synthetic Acceptance",
        "role": "AGENT",
        "user_group": "P3TEST",
        "campaigns": ["P3TST001"],
        "inbound_groups": ["TEST_IN"],
        "context": "codestra-echo-only",
        "approved_attributes": [],
    }
    key = f"synthetic-{args.employee_id}"
    results = {"phase": args.phase, "external_calls": 0}
    if args.phase == "provision":
        created = execute(
            service, principal, "create_user_disabled", key + "-user", base
        )
        replay = execute(
            service, principal, "create_user_disabled", key + "-user", base
        )
        if created != replay or created["state"] != "disabled":
            raise RuntimeError("disabled user creation was not idempotent")
        # The synthetic login password remains exclusively in the protected
        # staging secret file; it is never returned or persisted by this script.
        agent_password = args.agent_password_file.read_text().strip()
        if not agent_password:
            raise RuntimeError("protected synthetic agent password is empty")
        backend.mutate(
            "update_user",
            {"agent_user": args.username, "agent_pass": agent_password},
        )
        execute(
            service,
            principal,
            "assign_campaigns",
            key + "-campaigns",
            {"username": args.username, "campaigns": ["P3TST001"]},
        )
        execute(
            service,
            principal,
            "assign_inbound_groups",
            key + "-ingroups",
            {"username": args.username, "inbound_groups": ["TEST_IN"]},
        )
        phone = execute(
            service,
            principal,
            "create_phone_disabled",
            key + "-phone",
            {
                "username": args.username,
                "pool": "TRANSPORTATION",
                "extension": args.extension,
                "server_ip": "65.21.67.207",
                "full_name": base["full_name"],
            },
        )
        user_verified = execute(
            service,
            principal,
            "verify_user",
            key + "-verify-user",
            {"username": args.username},
        )
        phone_verified = execute(
            service,
            principal,
            "verify_phone",
            key + "-verify-phone",
            {"username": args.username},
        )
        execute(
            service,
            principal,
            "activate_user",
            key + "-activate-user",
            {"username": args.username},
        )
        execute(
            service,
            principal,
            "activate_phone",
            key + "-activate-phone",
            {"username": args.username},
        )
        results.update(
            {
                "create_user_disabled": "PASS",
                "idempotent_replay": "PASS",
                "campaign_assignment": "PASS",
                "inbound_group_assignment": "PASS",
                "create_phone_disabled": "PASS",
                "user_verified": user_verified["present"],
                "phone_verified": phone_verified["present"],
                "extension": phone["extension"],
                "activation": "PASS",
            }
        )
    elif args.phase == "suspend":
        execute(
            service,
            principal,
            "disable_phone",
            key + "-suspend-phone",
            {"username": args.username},
        )
        execute(
            service,
            principal,
            "disable_user",
            key + "-suspend-user",
            {"username": args.username},
        )
        results["suspension"] = "PASS"
    elif args.phase == "reactivate":
        execute(
            service,
            principal,
            "activate_user",
            key + "-reactivate-user",
            {"username": args.username},
        )
        execute(
            service,
            principal,
            "activate_phone",
            key + "-reactivate-phone",
            {"username": args.username},
        )
        results["reactivation"] = "PASS"
    elif args.phase == "terminate":
        execute(
            service,
            principal,
            "disable_phone",
            key + "-terminate-phone",
            {"username": args.username},
        )
        execute(
            service,
            principal,
            "disable_user",
            key + "-terminate-user",
            {"username": args.username},
        )
        execute(
            service,
            principal,
            "revoke_sip_secret",
            key + "-revoke",
            {"username": args.username},
        )
        if backend.endpoint(args.extension) is not None:
            raise RuntimeError("endpoint remains after termination")
        results["termination"] = "PASS_DISABLED_AND_REVOKED"
    else:
        reconciliation = execute(
            service, principal, "reconcile", key + "-reconcile", {}
        )
        results["reconciliation"] = reconciliation
    print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    main()
