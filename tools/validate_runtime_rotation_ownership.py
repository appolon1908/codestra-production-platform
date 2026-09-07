#!/usr/bin/env python3
"""Validate source ownership contracts; this does not certify live rotation."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONSUMERS = {
    "ODOO_OUTBOUND_HMAC_SECRET": {"control-plane-api", "control-plane-worker", "Odoo"},
    "KLYROW_WEBHOOK_SECRET": {
        "control-plane-api", "private-integration-gateway", "Klyrow",
        "codestra-email-reseller-api-1",
    },
}
ENVIRONMENT_CONSUMERS = {
    "ODOO_OUTBOUND_HMAC_SECRET": {
        "codestra-integration-control-plane-api-1",
        "codestra-integration-control-plane-worker-1",
        "odoo:codestra.webhook_secret",
    },
    "KLYROW_WEBHOOK_SECRET": {
        "codestra-integration-control-plane-api-1", "private-integration-gateway-1",
        "codestra-email-reseller-api-1", "klyrow-private-webhook-authority",
    },
}
RUNTIME_STORES = {
    "ODOO_OUTBOUND_HMAC_SECRET": {
        "/etc/codestra/secrets/control-plane.env": {
            "codestra-integration-control-plane-api-1",
            "codestra-integration-control-plane-worker-1",
        },
        "odoo:ir.config_parameter:codestra.webhook_secret": {"codestra-odoo-1"},
    },
    "KLYROW_WEBHOOK_SECRET": {
        "/etc/codestra/secrets/control-plane.env": {
            "codestra-integration-control-plane-api-1",
            "codestra-integration-control-plane-worker-1",
        },
        "/etc/kyqra-telnexa-integration/shared.env": {"private-integration-gateway-1"},
        "/etc/codestra/secrets/kyqra-telnexa/middleware.env": {
            "codestra-email-reseller-api-1"
        },
    },
}
CHECKS = {
    "all_consumers_quiesced", "all_stores_updated", "all_replicas_recreated",
    "new_auth_accepted", "old_auth_explicitly_rejected", "delivery_disabled",
    "rollback_validated", "independent_owner_approval",
}


def _exact_entries(document: dict, key: str) -> dict[str, dict]:
    entries = document.get(key)
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise ValueError(f"{key} must be a list of objects")
    ids = [item.get("secret_id") for item in entries]
    if len(ids) != len(set(ids)) or set(ids) != set(RUNTIME_CONSUMERS):
        raise ValueError("exact exposed-secret entries required")
    return {item["secret_id"]: item for item in entries}


def _validate_stores(secret_id: str, stores: object) -> None:
    if not isinstance(stores, list) or any(not isinstance(store, dict) for store in stores):
        raise ValueError("runtime stores must be objects")
    by_path = {store.get("path"): store for store in stores}
    if len(by_path) != len(stores) or set(by_path) != set(RUNTIME_STORES[secret_id]):
        raise ValueError("runtime store inventory incomplete")
    for path, expected_boundary in RUNTIME_STORES[secret_id].items():
        store = by_path[path]
        boundary = store.get("restart_boundary")
        if not isinstance(boundary, list) or set(boundary) != expected_boundary or len(boundary) != len(expected_boundary):
            raise ValueError("runtime store restart boundary is not exact")
        if path.startswith("/") and (store.get("owner"), store.get("mode")) != ("root:root", "0600"):
            raise ValueError("runtime environment store ownership is unsafe")


def validate(document: dict) -> None:
    if document.get("schema") != "codestra.runtime-secret-rotation-ownership.v1":
        raise ValueError("unsupported rotation ownership schema")
    entries = _exact_entries(document, "entries")
    for secret_id, entry in entries.items():
        if (entry.get("uid"), entry.get("gid"), entry.get("mode")) != (0, 0, "0600"):
            raise ValueError("root-owned mode-0600 environment policy required")
        if entry.get("storage") != "env_file_entry" or entry.get("host_path") != "/etc/codestra/secrets/control-plane.env":
            raise ValueError("shared environment storage must be explicit")
        _validate_stores(secret_id, entry.get("runtime_stores"))
        if entry.get("activation_allowed") is not False or entry.get("live_inventory_status") != "PENDING":
            raise ValueError("source contract cannot claim live approval")
        if entry.get("external_inventory_required") is not True:
            raise ValueError("peer inventory is mandatory")
        for field in ("accountable_owner", "rollout_owner", "peer_owner", "rotation_group"):
            if not entry.get(field):
                raise ValueError("rotation owner/group missing")
        if set(entry.get("required_checks", [])) != CHECKS:
            raise ValueError("rotation checks incomplete")
        consumers = entry.get("consumers")
        if not isinstance(consumers, list) or any(not isinstance(item, dict) for item in consumers):
            raise ValueError("consumer inventory must contain objects")
        names = [consumer.get("name") for consumer in consumers]
        if len(names) != len(set(names)) or set(names) != RUNTIME_CONSUMERS[secret_id]:
            raise ValueError("consumer inventory incomplete")
        for consumer in consumers:
            source = consumer.get("source")
            if not isinstance(source, str) or not (ROOT / source).is_file():
                raise ValueError("consumer source missing")
            if consumer["name"] not in {"Odoo", "Klyrow"} and (consumer.get("uid"), consumer.get("gid")) != (10001, 10001):
                raise ValueError("container ownership policy mismatch")
        if secret_id == "KLYROW_WEBHOOK_SECRET":
            proof = {
                "runtime_environment", "restart_boundary", "new_secret_acceptance",
                "old_secret_rejection", "rollback", "evidence",
            }
            expected_environments = {
                "private-integration-gateway": "/etc/kyqra-telnexa-integration/shared.env",
                "codestra-email-reseller-api-1": "/etc/codestra/secrets/kyqra-telnexa/middleware.env",
            }
            for name, environment in expected_environments.items():
                consumer = next(item for item in consumers if item["name"] == name)
                if consumer.get("runtime_environment") != environment or any(not consumer.get(field) for field in proof):
                    raise ValueError(f"{name} rotation proof is incomplete")
        if not isinstance(entry.get("procedure"), str) or not (ROOT / entry["procedure"]).is_file():
            raise ValueError("rotation procedure missing")
        aliases = {"CRM_ODOO_HMAC_SECRET", "codestra.webhook_secret"} if secret_id.startswith("ODOO") else {"KLYROW_WEBHOOK_SECRET_FILE"}
        if set(entry.get("aliases", [])) != aliases:
            raise ValueError("secret override inventory incomplete")


def validate_environment(document: dict) -> None:
    if document.get("schema_version") != 1 or document.get("approved_root") != "/etc/codestra/secrets":
        raise ValueError("unsupported environment ownership schema")
    if document.get("environment_file") != {
        "path": "/etc/codestra/secrets/control-plane.env", "owner": "root:root",
        "mode": "0600", "atomic_group": "control-plane-email-authorities",
    }:
        raise ValueError("primary environment file contract mismatch")
    entries = _exact_entries(document, "secrets")
    for secret_id, entry in entries.items():
        consumers = entry.get("consumers")
        if not isinstance(consumers, list) or len(consumers) != len(set(consumers)) or set(consumers) != ENVIRONMENT_CONSUMERS[secret_id]:
            raise ValueError("environment consumer inventory incomplete")
        checks = (entry.get("new_auth_check"), entry.get("old_auth_check"))
        if any(not isinstance(value, str) or not value for value in checks):
            raise ValueError("acceptance and rejection checks are required")
    files = document.get("environment_files")
    if not isinstance(files, list) or any(not isinstance(item, dict) for item in files):
        raise ValueError("environment file inventory required")
    paths = [item.get("path") for item in files]
    expected_paths = {path for stores in RUNTIME_STORES.values() for path in stores if path.startswith("/")}
    if len(paths) != len(set(paths)) or set(paths) != expected_paths:
        raise ValueError("environment file inventory incomplete")
    for item in files:
        if (item.get("owner"), item.get("mode")) != ("root:root", "0600"):
            raise ValueError("environment file ownership is unsafe")
        secret_ids = item.get("secret_ids")
        restart_boundary = item.get("restart_boundary")
        if not isinstance(secret_ids, list) or not secret_ids or not set(secret_ids) <= set(RUNTIME_CONSUMERS):
            raise ValueError("environment file secret inventory invalid")
        expected_boundary = set().union(*(RUNTIME_STORES[secret_id][item["path"]] for secret_id in secret_ids))
        if not isinstance(restart_boundary, list) or len(restart_boundary) != len(set(restart_boundary)) or set(restart_boundary) != expected_boundary:
            raise ValueError("environment file restart boundary mismatch")
    rollout = document.get("rollout")
    if not isinstance(rollout, dict) or any(not rollout.get(field) for field in ("success_order", "rollback_order", "required_evidence")):
        raise ValueError("rotation rollout contract incomplete")


if __name__ == "__main__":
    runtime = json.loads((ROOT / "config/runtime-secret-rotation-ownership.json").read_text())
    environment = json.loads((ROOT / "config/environment-secret-rotation-ownership.json").read_text())
    validate(runtime)
    validate_environment(environment)
    print("ROTATION_OWNERSHIP_CONTRACT=PASS LIVE_ROTATION=NOT_VERIFIED")
