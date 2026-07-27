#!/usr/bin/env python3
"""Fail-closed gate for a single staging automatic-campaign lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


FALSE_FLAGS = (
    "N8N_WORKFLOW_ACTIVE",
    "LEAD_PUBLICATION",
    "AGENT_SYNC",
    "LIVE_CALL_CONTROL",
    "PRODUCTION_DIALING",
    "EXTERNAL_COMMUNICATION",
)
PRIVATE_ADAPTER_IP = ipaddress.ip_address("10.40.0.2")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def validate(values: dict[str, str], resolver=socket.gethostbyname_ex) -> None:
    if values.get("ENVIRONMENT") not in {"staging", "test"}:
        raise RuntimeError("staging_or_test_environment_required")
    list_id = int(values["VICIDIAL_LIST_ID"])
    if not 91000 <= list_id <= 91999:
        raise RuntimeError("list_id_outside_staging_range")
    if values.get("TEST_ENDPOINT") != "6101":
        raise RuntimeError("approved_test_endpoint_required")
    if any(values.get(flag, "").lower() != "false" for flag in FALSE_FLAGS):
        raise RuntimeError("all_action_flags_must_be_false")
    if any(key in values for key in ("TELEPHONE_NUMBER", "CUSTOMER_PHONE")):
        raise RuntimeError("telephone_numbers_forbidden")
    parsed = urlsplit(values["ADAPTER_URL"])
    if parsed.scheme != "https" or parsed.hostname != "edge.internal.codestra.agency":
        raise RuntimeError("private_adapter_hostname_required")
    addresses = resolver(parsed.hostname)[2]
    if not addresses or any(ipaddress.ip_address(item) != PRIVATE_ADAPTER_IP for item in addresses):
        raise RuntimeError("adapter_must_resolve_only_to_private_ip")


def readiness(values: dict[str, str]) -> dict:
    context = ssl.create_default_context(cafile=values["ADAPTER_CA_FILE"])
    context.load_cert_chain(
        values["ADAPTER_CLIENT_CERT_FILE"], values["ADAPTER_CLIENT_KEY_FILE"]
    )
    request = urllib.request.Request(values["ADAPTER_URL"] + "/health/ready")
    try:
        response = urllib.request.urlopen(request, context=context, timeout=8)
    except urllib.error.HTTPError as error:
        response = error
    body = response.read(65537)
    if len(body) > 65536:
        raise RuntimeError("adapter_readiness_response_too_large")
    document = json.loads(body)
    if response.status != 200 or document.get("status") != "ready":
        raise RuntimeError("private_adapter_not_ready")
    return document


def redacted_manifest(values: dict[str, str]) -> dict:
    manifest = {
        "schema_version": "campaign-provisioning.v1",
        "environment": values["ENVIRONMENT"],
        "business_unit": values["BUSINESS_UNIT"],
        "canonical_campaign": values["CANONICAL_CAMPAIGN"],
        "vicidial": {
            "campaign_id": values["VICIDIAL_CAMPAIGN"],
            "list_id": int(values["VICIDIAL_LIST_ID"]),
            "active": False,
            "test_agent": values["TEST_AGENT"],
            "test_endpoint": values["TEST_ENDPOINT"],
        },
        "n8n": {"active": False},
        "lead": {"synthetic": True, "telephone_number": None},
        "transfer_policy": "same-campaign-only",
        "feature_flags": {key.lower(): False for key in FALSE_FLAGS},
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return {"manifest": manifest, "sha256": hashlib.sha256(encoded).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    values = load_env(args.config)
    result = {"status": "BLOCKED", **redacted_manifest(values)}
    try:
        validate(values)
        result["adapter_readiness"] = readiness(values)
        result["status"] = "READY_TO_EXECUTE"
    except Exception as exc:
        result["blocker"] = str(exc)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["status"] == "READY_TO_EXECUTE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
