#!/usr/bin/env python3
"""Fail-closed Odoo/VICIdial campaign reconciler.

The tool consumes the authoritative Odoo crosswalk CSV.  It never activates a
campaign, creates a customer list, changes a DID, loads a hopper, or enables
autodial.  Production apply is explicit and uses the private operator SSH path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campaign_provisioning import PrivateAdapterClient, PrivateAdapterConfig

SCHEMA = "asterisk"

def run(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        args, input=input_text, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {args[0]}")
    return result.stdout


def read_mysql(sql: str) -> str:
    if not sql.lstrip().upper().startswith("SELECT "):
        raise RuntimeError("reconciler SSH database path is read-only")
    return run("ssh", "codestra-vicidial", "sudo", "mysql", "-N", "-B", input_text=sql)


def actual_state() -> dict[str, dict[str, dict[str, str]]]:
    queries = {
        "campaigns": (
            "SELECT campaign_id,campaign_name,active,dial_method,local_call_time,"
            "auto_dial_level,hopper_level,campaign_recording,scheduled_callbacks,"
            f"campaign_description FROM {SCHEMA}.vicidial_campaigns"
        ),
        "groups": (
            "SELECT user_group,group_name,allowed_campaigns "
            f"FROM {SCHEMA}.vicidial_user_groups"
        ),
        "ingroups": (
            f"SELECT group_id,group_name,active FROM {SCHEMA}.vicidial_inbound_groups"
        ),
        "statuses": (
            "SELECT CONCAT(campaign_id,':',status),status_name,selectable,"
            f"human_answered,category FROM {SCHEMA}.vicidial_campaign_statuses"
        ),
    }
    fields = {
        "campaigns": ("id", "name", "active", "dial_method", "call_time", "auto", "hopper", "recording", "callbacks", "description"),
        "groups": ("id", "name", "allowed"),
        "ingroups": ("id", "name", "active"),
        "statuses": ("id", "name", "selectable", "human_answered", "category"),
    }
    state = {}
    for kind, sql in queries.items():
        rows = {}
        for line in read_mysql(sql + ";").splitlines():
            values = line.split("\t")
            row = dict(zip(fields[kind], values))
            rows[row["id"]] = row
        state[kind] = rows
    return state


def desired(path: Path) -> list[dict[str, str]]:
    rows = list(csv.DictReader(path.open()))
    if len(rows) != 105:
        raise RuntimeError(f"expected 105 Odoo classifications, found {len(rows)}")
    if any(row["CLASSIFICATION"] == "UNCLASSIFIED" for row in rows):
        raise RuntimeError("unclassified Odoo campaign")
    return [row for row in rows if row["EXPECTED_VICIDIAL_CAMPAIGN"]]


def build_plan(rows: list[dict[str, str]], state) -> dict:
    creates, unchanged, safety_updates, blockers, legacy_adoptions = [], [], [], [], []
    group_members: dict[str, list[str]] = defaultdict(list)
    ingroups = {}
    for row in rows:
        actual = row["EXPECTED_VICIDIAL_CAMPAIGN"]
        code = row["CODE"]
        group = row["EXPECTED_USER_GROUP"]
        ingroup = row["EXPECTED_INGROUP"]
        group_members[group].append(actual)
        if ingroup:
            ingroups[ingroup] = code
        current = state["campaigns"].get(actual)
        if current is None:
            creates.append({"physical_id": actual, "canonical_code": code})
        elif current["active"] != "N" or current["auto"] not in ("0", "0.0"):
            blockers.append({"resource": actual, "reason": "existing campaign is dialable"})
        elif current["description"] != "CODESTRA:" + code or any((
            current["name"] != code,
            current["dial_method"] != "MANUAL",
            current["call_time"] != "9am-5pm",
            current["recording"] != "ONDEMAND",
            current["callbacks"] != "N",
        )):
            legacy_adoptions.append({"resource": actual, "reason": "explicit fingerprint-gated migration"})
        elif current["hopper"] != "0":
            safety_updates.append({"physical_id": actual, "hopper_before": current["hopper"]})
        else:
            unchanged.append(actual)
    group_creates = [
        {"id": group, "campaigns": sorted(set(members))}
        for group, members in sorted(group_members.items())
        if group not in state["groups"]
    ]
    group_updates = []
    for group, members in sorted(group_members.items()):
        current = state["groups"].get(group)
        if not current:
            continue
        tokens = set((current.get("allowed") or "").strip().strip("-").split())
        missing = sorted(set(members) - tokens)
        if missing:
            group_updates.append({"id": group, "campaigns": sorted(tokens | set(members))})
    ingroup_creates = [
        {"id": group, "name": name}
        for group, name in sorted(ingroups.items())
        if group not in state["ingroups"]
    ]
    certification_preserved_ingroups = {
        row["EXPECTED_INGROUP"] for row in rows
        if row["CODE"] == "TEST_SYN" and row["EXPECTED_INGROUP"]
    }
    active_ingroup_blockers = [
        {"resource": group, "reason": "existing inbound group is active"}
        for group in sorted(ingroups)
        if group in state["ingroups"] and state["ingroups"][group]["active"] != "N"
        and group not in certification_preserved_ingroups
    ]
    blockers.extend(active_ingroup_blockers)
    # TEST_SYN dispositions are campaign-scoped. Existing global VICIdial
    # statuses are reused where possible; only missing semantic codes are made.
    required_statuses = {
        "TEST_SYN:ANS": ("Answered", "Y", "HUMAN"),
        "TEST_SYN:APPT": ("Appointment", "Y", "CALLBACK"),
        "TEST_SYN:WN": ("Wrong Number", "N", "UNWORKABLE"),
    }
    status_creates = [
        {
            "id": key,
            "campaign_id": key.split(":", 1)[0],
            "status": key.split(":", 1)[1],
            "name": values[0],
            "human_answered": values[1],
            "category": values[2],
        }
        for key, values in required_statuses.items()
        if key not in state["statuses"]
    ]
    return {
        "campaign_creates": creates,
        "campaign_unchanged": unchanged,
        "campaign_safety_updates": safety_updates,
        "campaign_legacy_adoptions": legacy_adoptions,
        "group_creates": group_creates,
        "group_updates": group_updates,
        "ingroup_creates": ingroup_creates,
        "ingroup_safety_updates": [],
        "status_creates": status_creates,
        "blockers": blockers,
    }


def adapter_command(row: dict[str, str], state: dict | None = None, *,
                    plan_sha256: str | None = None,
                    authorization_reference: str | None = None,
                    backup_reference: str | None = None) -> dict:
    code = row["CODE"]
    business_unit = code.split("-", 1)[0] if code != "TEST_SYN" else "TEST"
    direction = "inbound" if code.endswith("-IN") else "outbound"
    current_group = state and state["groups"].get(row["EXPECTED_USER_GROUP"])
    group_name = current_group["name"] if current_group else "Codestra " + row["EXPECTED_USER_GROUP"]
    groups = [{
        "code": row["EXPECTED_USER_GROUP"],
        "name": group_name,
        "kind": "user",
        "active": False,
    }]
    preserve_certification_ingroup = (
        code == "TEST_SYN" and row["EXPECTED_INGROUP"] == "TEST_IN"
        and state and state["ingroups"].get("TEST_IN", {}).get("active") == "Y"
    )
    if row["EXPECTED_INGROUP"] and not preserve_certification_ingroup:
        groups.append({
            "code": row["EXPECTED_INGROUP"], "name": code,
            "kind": "inbound", "active": False,
        })
    dispositions = []
    if code == "TEST_SYN":
        dispositions = [
            {"code": "ANS", "name": "Answered", "human_answered": True, "category": "HUMAN"},
            {"code": "APPT", "name": "Appointment", "human_answered": True, "category": "CALLBACK"},
            {"code": "WN", "name": "Wrong Number", "human_answered": False, "category": "UNWORKABLE"},
        ]
    campaign = {
            "canonical_id": code,
            "actual_id": row["EXPECTED_VICIDIAL_CAMPAIGN"],
            "name": code,
            "business_unit": business_unit,
            "direction": direction,
            "active": False,
            "dial_method": "MANUAL",
            "call_time": "9am-5pm",
            "recording_policy": "ONDEMAND",
            "callback_enabled": False,
            "lists": [],
            "groups": groups,
            "scripts": [],
            "dispositions": dispositions,
            "transfer_targets": [],
            "reporting_mapping": "ODOO:" + code,
            "recording_policy_reference": "ODOO:ONDEMAND",
        }
    current = state and state["campaigns"].get(row["EXPECTED_VICIDIAL_CAMPAIGN"])
    if current and current["description"] != "CODESTRA:" + code:
        observed = {
            "campaign_id": current["id"], "campaign_name": current["name"],
            "active": current["active"], "dial_method": current["dial_method"],
            "local_call_time": current["call_time"],
            "campaign_recording": current["recording"],
            "scheduled_callbacks": current["callbacks"],
            "campaign_description": current["description"],
        }
        campaign["adopt_existing_sha256"] = hashlib.sha256(
            json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    command = {
        "context": {
            "correlation_id": "campaign-reconcile-" + row["EXPECTED_VICIDIAL_CAMPAIGN"],
            "actor": "codestra-campaign-reconcile",
            "reason": "approved disabled campaign reconciliation",
            "requested_at": datetime.now(timezone.utc).isoformat(),
        },
        "campaign": campaign,
    }
    if plan_sha256 or authorization_reference or backup_reference:
        if not all((plan_sha256, authorization_reference, backup_reference)):
            raise RuntimeError("complete reconciliation request binding required")
        command.update({
            "plan_sha256": plan_sha256,
            "authorization_reference": authorization_reference,
            "backup_reference": backup_reference,
        })
    return command


def apply_via_adapter(rows: list[dict[str, str]], state: dict, client: PrivateAdapterClient,
                      *, plan_sha256: str, authorization_reference: str,
                      backup_reference: str) -> list[dict]:
    results = []
    for row in rows:
        key = "campaign-reconcile:" + row["EXPECTED_VICIDIAL_CAMPAIGN"]
        command = adapter_command(
            row, state, plan_sha256=plan_sha256,
            authorization_reference=authorization_reference,
            backup_reference=backup_reference,
        )
        results.append(client.reconcile_campaign(key, command))
    return results


def verify(rows: list[dict[str, str]], state) -> dict:
    errors = []
    required_groups: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        actual = row["EXPECTED_VICIDIAL_CAMPAIGN"]
        campaign = state["campaigns"].get(actual)
        if not campaign:
            errors.append(f"missing campaign {actual}")
        elif campaign["active"] != "N" or campaign["auto"] not in ("0", "0.0") or campaign["hopper"] != "0":
            errors.append(f"dialable campaign {actual}")
        if row["EXPECTED_USER_GROUP"] not in state["groups"]:
            errors.append(f"missing group {row['EXPECTED_USER_GROUP']}")
        else:
            required_groups[row["EXPECTED_USER_GROUP"]].add(actual)
        if row["EXPECTED_INGROUP"] and row["EXPECTED_INGROUP"] not in state["ingroups"]:
            errors.append(f"missing ingroup {row['EXPECTED_INGROUP']}")
        elif (row["EXPECTED_INGROUP"] and
              state["ingroups"][row["EXPECTED_INGROUP"]]["active"] != "N" and
              not (row["CODE"] == "TEST_SYN" and row["EXPECTED_INGROUP"] == "TEST_IN")):
            errors.append(f"active ingroup {row['EXPECTED_INGROUP']}")
    for group, campaigns in required_groups.items():
        tokens = set((state["groups"][group].get("allowed") or "").strip().strip("-").split())
        missing = campaigns - tokens
        if missing:
            errors.append(f"group {group} missing campaigns {','.join(sorted(missing))}")
    for status in ("ANS", "APPT", "WN"):
        if f"TEST_SYN:{status}" not in state["statuses"]:
            errors.append(f"missing TEST_SYN status {status}")
    return {"errors": errors, "verified": len(rows) if not errors else 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("audit", "plan", "apply", "verify"))
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply-token")
    parser.add_argument("--schema", default="asterisk")
    parser.add_argument("--adapter-url")
    parser.add_argument("--adapter-ca-file")
    parser.add_argument("--adapter-client-cert-file")
    parser.add_argument("--adapter-client-key-file")
    parser.add_argument("--adapter-hmac-file")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--authorization-reference")
    parser.add_argument("--backup-reference")
    args = parser.parse_args()
    global SCHEMA
    if not args.schema.replace("_", "").isalnum():
        raise RuntimeError("invalid schema name")
    SCHEMA = args.schema
    rows = desired(args.crosswalk)
    state = actual_state()
    plan = build_plan(rows, state)
    result = {"mode": args.mode, "desired": len(rows), "plan": plan}
    if plan["blockers"]:
        result["status"] = "BLOCKED_SECURITY_BOUNDARY"
    elif args.mode == "apply":
        if args.apply_token != "OWNER_FULL_AUTONOMY=YES":
            raise RuntimeError("explicit owner apply token required")
        adapter_values = (
            args.adapter_url, args.adapter_ca_file, args.adapter_client_cert_file,
            args.adapter_client_key_file, args.adapter_hmac_file,
        )
        if not all(adapter_values):
            raise RuntimeError("restricted adapter mTLS/HMAC configuration required")
        client = PrivateAdapterClient(PrivateAdapterConfig(
            base_url=args.adapter_url,
            ca_file=args.adapter_ca_file,
            client_cert_file=args.adapter_client_cert_file,
            client_key_file=args.adapter_client_key_file,
            hmac_file=args.adapter_hmac_file,
        ))
        bindings = (args.plan_sha256, args.authorization_reference, args.backup_reference)
        if not all(bindings):
            raise RuntimeError("plan, owner authorization, and backup bindings required")
        result["adapter_results"] = apply_via_adapter(
            rows, state, client, plan_sha256=args.plan_sha256,
            authorization_reference=args.authorization_reference,
            backup_reference=args.backup_reference,
        )
        checked = verify(rows, actual_state())
        result.update(checked, status="PASS" if not checked["errors"] else "FAIL")
    elif args.mode == "verify":
        checked = verify(rows, state)
        result.update(checked, status="PASS" if not checked["errors"] else "DRIFT")
    else:
        result["status"] = "PASS"
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload)
    sys.stdout.write(payload)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
