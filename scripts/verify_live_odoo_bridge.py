#!/usr/bin/env python3
"""Run inside the control-plane container to verify the synthetic Odoo bridge."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid


BASE = os.environ.get("ODOO_BASE_URL", "http://codestra-odoo-1:8069").rstrip("/")
SECRET = os.environ["ODOO_OUTBOUND_HMAC_SECRET"]
TENANT = os.environ.get("CONTROL_PLANE_TENANT_ID", "codestra-production")
PREFIX = "CODESTRA-INTEGRATION-TEST-"


def call(method: str, path: str, payload: dict | None, event_id: str, idem: str,
         correlation: str, *, secret: str = SECRET) -> tuple[int, dict]:
    raw = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    stamp = str(int(time.time()))
    canonical = b"\n".join((stamp.encode(), event_id.encode(), method.encode(), path.encode(), raw))
    signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    request = urllib.request.Request(BASE + path, raw if method != "GET" else None, {
        "Content-Type": "application/json",
        "X-Codestra-Timestamp": stamp,
        "X-Codestra-Event-ID": event_id,
        "X-Codestra-Signature": "sha256=" + signature,
        "X-Tenant-ID": TENANT,
        "X-Correlation-ID": correlation,
        "Idempotency-Key": idem,
    }, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> None:
    stamp = uuid.uuid4().hex
    tag = PREFIX + stamp
    correlation = "odoo-bridge-live-" + stamp
    results: dict[str, object] = {"tag": tag, "correlation_id": correlation}

    with urllib.request.urlopen(BASE + "/web/health", timeout=5) as response:
        results["health"] = response.status

    create_body = {"name": tag, "external_id": tag, "email": stamp + "@example.invalid"}
    create_event = "mw-create-" + stamp
    status, created = call("POST", "/codestra/middleware/v1/contacts", create_body,
                           create_event, "idem-create-" + stamp, correlation)
    assert status == 201 and created["correlation_id"] == correlation
    partner_id = int(created["partner_id"])
    results["create"] = status

    path = f"/codestra/middleware/v1/contacts/{partner_id}"
    status, read = call("GET", path, None, "mw-read-" + stamp,
                        "idem-read-" + stamp, correlation)
    assert status == 200 and read["external_id"] == tag
    results["read"] = status

    update_body = {"phone": "+1999555" + stamp[:4]}
    status, updated = call("PATCH", path, update_body, "mw-update-" + stamp,
                           "idem-update-" + stamp, correlation)
    assert status == 200 and updated["phone"] == update_body["phone"]
    results["update"] = status

    activity_path = path + "/activities"
    status, activity = call("POST", activity_path, {"summary": tag + "-ACTIVITY"},
                            "mw-activity-" + stamp, "idem-activity-" + stamp, correlation)
    assert status == 201 and activity["correlation_id"] == correlation
    results["activity"] = status
    results["activity_id"] = int(activity["activity_id"])

    status_path = path + "/status"
    status, changed = call("POST", status_path, {"status": "inactive"},
                           "mw-status-" + stamp, "idem-status-" + stamp, correlation)
    assert status == 200 and changed["status"] == "inactive"
    results["status_update"] = status

    duplicate_event = "mw-create-retry-" + stamp
    status, duplicate = call("POST", "/codestra/middleware/v1/contacts", create_body,
                             duplicate_event, "idem-create-" + stamp, correlation)
    assert status == 200 and duplicate["duplicate"] is True and int(duplicate["partner_id"]) == partner_id
    results["idempotent_retry"] = status

    status, replay = call("POST", "/codestra/middleware/v1/contacts", create_body,
                          create_event, "idem-create-replay-" + stamp, correlation)
    assert status == 409 and replay["error"] == "replayed_event_id"
    results["replay_rejection"] = status

    status, invalid = call("GET", path, None, "mw-invalid-" + stamp,
                           "idem-invalid-" + stamp, correlation, secret="invalid")
    assert status == 401 and invalid["error"] == "invalid_signature"
    results["invalid_auth"] = status
    results["partner_id"] = partner_id
    print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    main()
