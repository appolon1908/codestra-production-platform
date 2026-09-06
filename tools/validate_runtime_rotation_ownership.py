#!/usr/bin/env python3
"""Validate the source ownership contract; this does not certify live rotation."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "ODOO_OUTBOUND_HMAC_SECRET": {"control-plane-api", "control-plane-worker", "Odoo"},
    "KLYROW_WEBHOOK_SECRET": {"control-plane-api", "private-integration-gateway", "Klyrow", "codestra-email-reseller-api-1"},
}
CHECKS = {
    "all_consumers_quiesced", "all_stores_updated", "all_replicas_recreated",
    "new_auth_accepted", "old_auth_explicitly_rejected", "delivery_disabled",
    "rollback_validated", "independent_owner_approval",
}


def validate(document: dict) -> None:
    if document.get("schema") != "codestra.runtime-secret-rotation-ownership.v1":
        raise ValueError("unsupported rotation ownership schema")
    entries = document.get("entries", [])
    if len(entries) != len(EXPECTED) or {e["secret_id"] for e in entries} != set(EXPECTED):
        raise ValueError("exact exposed-secret entries required")
    for entry in entries:
        if (entry.get("uid"), entry.get("gid"), entry.get("mode")) != (0, 0, "0600"):
            raise ValueError("root-owned mode-0600 environment policy required")
        if entry.get("storage") != "env_file_entry" or entry.get("host_path") != "/etc/codestra/secrets/control-plane.env":
            raise ValueError("shared environment storage must be explicit")
        stores = entry.get("runtime_stores", [])
        if not stores or any(not store.get("restart_boundary") for store in stores):
            raise ValueError("runtime stores and restart boundaries are required")
        if entry.get("activation_allowed") is not False or entry.get("live_inventory_status") != "PENDING":
            raise ValueError("source contract cannot claim live approval")
        if entry.get("external_inventory_required") is not True:
            raise ValueError("peer inventory is mandatory")
        for field in ("accountable_owner", "rollout_owner", "peer_owner", "rotation_group"):
            if not entry.get(field):
                raise ValueError("rotation owner/group missing")
        if set(entry.get("required_checks", [])) != CHECKS:
            raise ValueError("rotation checks incomplete")
        consumers = entry.get("consumers", [])
        if len(consumers) != len(EXPECTED[entry["secret_id"]]) or {c["name"] for c in consumers} != EXPECTED[entry["secret_id"]]:
            raise ValueError("consumer inventory incomplete")
        for consumer in consumers:
            if not (ROOT / consumer["source"]).is_file():
                raise ValueError("consumer source missing")
            if consumer["name"] not in {"Odoo", "Klyrow"} and (consumer["uid"], consumer["gid"]) != (10001, 10001):
                raise ValueError("container ownership policy mismatch")
        if entry["secret_id"] == "KLYROW_WEBHOOK_SECRET":
            reseller = next((c for c in consumers if c["name"] == "codestra-email-reseller-api-1"), None)
            if not reseller or reseller.get("runtime_environment") != "/etc/codestra/secrets/kyqra-telnexa/middleware.env":
                raise ValueError("email reseller environment store missing")
            proof = {"restart_boundary", "new_secret_acceptance", "old_secret_rejection", "rollback", "evidence"}
            if any(not reseller.get(field) for field in proof):
                raise ValueError("email reseller rotation proof is incomplete")
            store = next((s for s in stores if s.get("path") == reseller["runtime_environment"]), None)
            if not store or store.get("restart_boundary") != ["codestra-email-reseller-api-1"]:
                raise ValueError("email reseller restart boundary is not exact")
        if not (ROOT / entry["procedure"]).is_file():
            raise ValueError("rotation procedure missing")
        required_aliases = {"CRM_ODOO_HMAC_SECRET", "codestra.webhook_secret"} if entry["secret_id"].startswith("ODOO") else {"KLYROW_WEBHOOK_SECRET_FILE"}
        if set(entry.get("aliases", [])) != required_aliases:
            raise ValueError("secret override inventory incomplete")


if __name__ == "__main__":
    validate(json.loads((ROOT / "config/runtime-secret-rotation-ownership.json").read_text()))
    print("ROTATION_OWNERSHIP_CONTRACT=PASS LIVE_ROTATION=NOT_VERIFIED")
