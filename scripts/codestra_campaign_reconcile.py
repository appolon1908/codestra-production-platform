#!/usr/bin/env python3
"""Fail-closed Odoo/VICIdial campaign reconciler.

The tool consumes the authoritative Odoo crosswalk CSV.  It never activates a
campaign, creates a customer list, changes a DID, loads a hopper, or enables
autodial.  Production apply is explicit and uses the private operator SSH path.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

SCHEMA = "asterisk"

def run(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        args, input=input_text, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {args[0]}")
    return result.stdout


def quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def mysql(sql: str) -> str:
    return run("ssh", "codestra-vicidial", "sudo", "mysql", "-N", "-B", input_text=sql)


def actual_state() -> dict[str, dict[str, dict[str, str]]]:
    queries = {
        "campaigns": (
            "SELECT campaign_id,campaign_name,active,dial_method,local_call_time,"
            f"auto_dial_level,hopper_level FROM {SCHEMA}.vicidial_campaigns"
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
        "campaigns": ("id", "name", "active", "dial_method", "call_time", "auto", "hopper"),
        "groups": ("id", "name", "allowed"),
        "ingroups": ("id", "name", "active"),
        "statuses": ("id", "name", "selectable", "human_answered", "category"),
    }
    state = {}
    for kind, sql in queries.items():
        rows = {}
        for line in mysql(sql + ";").splitlines():
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
    creates, unchanged, safety_updates, blockers = [], [], [], []
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
        elif current["hopper"] != "0":
            safety_updates.append({"physical_id": actual, "hopper_before": current["hopper"]})
        else:
            unchanged.append(actual)
    group_creates = [
        {"id": group, "campaigns": sorted(set(members))}
        for group, members in sorted(group_members.items())
        if group not in state["groups"]
    ]
    ingroup_creates = [
        {"id": group, "name": name}
        for group, name in sorted(ingroups.items())
        if group not in state["ingroups"]
    ]
    ingroup_safety_updates = [
        {"id": group}
        for group in sorted(ingroups)
        if group in state["ingroups"] and state["ingroups"][group]["active"] != "N"
    ]
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
        "group_creates": group_creates,
        "ingroup_creates": ingroup_creates,
        "ingroup_safety_updates": ingroup_safety_updates,
        "status_creates": status_creates,
        "blockers": blockers,
    }


def sql_for(plan: dict) -> str:
    statements = [f"USE `{SCHEMA}`;", "LOCK TABLES vicidial_campaigns WRITE, vicidial_user_groups WRITE, vicidial_inbound_groups WRITE, vicidial_campaign_statuses WRITE;"]
    for item in plan["campaign_creates"]:
        statements.append(
            "INSERT INTO vicidial_campaigns"
            "(campaign_id,campaign_name,active,dial_method,local_call_time,"
            "campaign_recording,scheduled_callbacks,campaign_description,hopper_level,auto_dial_level) VALUES("
            + ",".join((quote(item["physical_id"]), quote(item["canonical_code"]), "'N'", "'MANUAL'", "'9am-5pm'", "'ONDEMAND'", "'N'", quote("CODESTRA:" + item["canonical_code"]), "0", "'0'"))
            + ");"
        )
    for item in plan.get("campaign_safety_updates", []):
        statements.append(
            "UPDATE vicidial_campaigns SET active='N',auto_dial_level='0',hopper_level=0 WHERE campaign_id="
            + quote(item["physical_id"]) + ";"
        )
    for item in plan["group_creates"]:
        allowed = " " + " ".join(item["campaigns"]) + " -"
        statements.append(
            "INSERT INTO vicidial_user_groups(user_group,group_name,allowed_campaigns) VALUES("
            + ",".join((quote(item["id"]), quote("Codestra " + item["id"]), quote(allowed))) + ");"
        )
    for item in plan["ingroup_creates"]:
        statements.append(
            "INSERT INTO vicidial_inbound_groups(group_id,group_name,active,group_color,group_handling,call_time_id) VALUES("
            + ",".join((quote(item["id"]), quote(item["name"]), "'N'", "'white'", "'PHONE'", "'9am-5pm'")) + ");"
        )
    for item in plan.get("ingroup_safety_updates", []):
        statements.append(
            "UPDATE vicidial_inbound_groups SET active='N' WHERE group_id="
            + quote(item["id"]) + ";"
        )
    for item in plan.get("status_creates", []):
        statements.append(
            "INSERT INTO vicidial_campaign_statuses"
            "(campaign_id,status,status_name,selectable,human_answered,category) VALUES("
            + ",".join((quote(item["campaign_id"]), quote(item["status"]), quote(item["name"]), "'Y'", quote(item["human_answered"]), quote(item["category"])))
            + ");"
        )
    statements.extend(("UNLOCK TABLES;", "SELECT 'APPLY_COMPLETE';"))
    return "\n".join(statements) + "\n"


def verify(rows: list[dict[str, str]], state) -> dict:
    errors = []
    for row in rows:
        actual = row["EXPECTED_VICIDIAL_CAMPAIGN"]
        campaign = state["campaigns"].get(actual)
        if not campaign:
            errors.append(f"missing campaign {actual}")
        elif campaign["active"] != "N" or campaign["auto"] not in ("0", "0.0") or campaign["hopper"] != "0":
            errors.append(f"dialable campaign {actual}")
        if row["EXPECTED_USER_GROUP"] not in state["groups"]:
            errors.append(f"missing group {row['EXPECTED_USER_GROUP']}")
        if row["EXPECTED_INGROUP"] and row["EXPECTED_INGROUP"] not in state["ingroups"]:
            errors.append(f"missing ingroup {row['EXPECTED_INGROUP']}")
        elif row["EXPECTED_INGROUP"] and state["ingroups"][row["EXPECTED_INGROUP"]]["active"] != "N":
            errors.append(f"active ingroup {row['EXPECTED_INGROUP']}")
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
        mysql(sql_for(plan))
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
