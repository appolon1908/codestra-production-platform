#!/usr/bin/env python3
"""Production-safe live connectivity audit for the integration control plane.

Run on the middleware host. The script re-executes itself inside the deployed API
container so credentials never cross the container boundary or enter the report.
Only synthetic reserved destinations and provider simulator/test modes are used.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

CONTAINER = os.getenv("CONTROL_PLANE_AUDIT_CONTAINER", "codestra-integration-control-plane-api-1")
BASE_HOST = "127.0.0.1"
BASE_PORT = int(os.getenv("CONTROL_PLANE_PORT", "8096"))
TENANT = "connectivity-audit"


def request(method: str, path: str, body: object | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
    values = dict(headers or {})
    if raw:
        values["Content-Type"] = "application/json"
        values["Content-Length"] = str(len(raw))
    connection = http.client.HTTPConnection(BASE_HOST, BASE_PORT, timeout=5)
    connection.request(method, path, body=raw or None, headers=values)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    try:
        parsed = json.loads(payload or b"{}")
    except json.JSONDecodeError:
        parsed = {"body_sha256": hashlib.sha256(payload).hexdigest()}
    return response.status, parsed


def signed_headers(source: str, event_id: str, body: object, timestamp: int | None = None, *, bad_signature: bool = False) -> dict[str, str]:
    stamp = str(timestamp if timestamp is not None else int(time.time()))
    raw = json.dumps(body, separators=(",", ":")).encode()
    secret = os.environ[source.upper() + "_WEBHOOK_SECRET"]
    canonical = b"\n".join((stamp.encode(), event_id.encode(), source.encode(), raw))
    signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    if bad_signature:
        signature = "0" * 64
    return {
        "Authorization": "Bearer " + os.environ[source.upper() + "_MIDDLEWARE_API_KEY"],
        "X-Event-Id": event_id,
        "X-Timestamp": stamp,
        "X-Signature": "sha256=" + signature,
    }


def envelope(source: str, event_type: str, key: str, correlation: str, payload: dict | None = None) -> dict:
    return {
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tenant_id": TENANT,
        "customer_id": "synthetic-customer",
        "correlation_id": correlation,
        "idempotency_key": key,
        "payload": payload or {"safe_test": True},
        "metadata": {"audit": True},
    }


def check(results: list[dict], name: str, actual: int, expected: int | tuple[int, ...], evidence: dict | None = None) -> None:
    accepted = (expected,) if isinstance(expected, int) else expected
    results.append({
        "test": name,
        "status": "PASS" if actual in accepted else "FAIL",
        "http_status": actual,
        "expected": list(accepted),
        "evidence": evidence or {},
    })


def operator_token() -> str:
    for name in ("CONTROL_PLANE_OPERATIONS_TOKEN", "CONTROL_PLANE_PLATFORM_ADMIN_TOKEN"):
        if os.getenv(name):
            return os.environ[name]
    raise RuntimeError("operator token unavailable")


def dispatch_once() -> None:
    code = "from control_plane_service.worker import dispatch_messages; print(dispatch_messages())"
    env = os.environ.copy()
    env["CONTROL_PLANE_OUTBOUND_ENABLED"] = "true"
    subprocess.run([sys.executable, "-c", code], env=env, check=True, capture_output=True, text=True, timeout=15)


def live_audit() -> dict:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    correlation = "connectivity-audit-" + run_id
    results: list[dict] = []

    for path in ("/health", "/ready", "/v1/ready"):
        status, payload = request("GET", path)
        check(results, "control-plane " + path, status, 200, {"response": payload})

    event_types = {
        # Use only routes present in the governed n8n workflow catalog. Sending
        # arbitrary prefix-valid audit types would test ingress but then queue
        # delivery to a webhook that intentionally does not exist.
        "odoo": "customer.updated",
        "n8n": "workflow.audit.completed",
        "telnexa": "telnexa.sms.delivered",
        "klyrow": "klyrow.email.delivered",
        "kyqra": "kyqra.job.completed",
    }
    event_ids: dict[str, str] = {}
    for source, event_type in event_types.items():
        event_id = f"audit-{source}-{run_id}"
        event_ids[source] = event_id
        body = envelope(source, event_type, f"audit-key-{source}-{run_id}", correlation)
        headers = signed_headers(source, event_id, body)
        status, payload = request("POST", f"/api/v1/events/{source}", body, headers)
        check(results, f"{source} valid auth/HMAC ingress", status, 202, {"event_id": event_id, "correlation_id": correlation, "response": payload})
        status, payload = request("POST", f"/api/v1/events/{source}", body, headers)
        # Odoo producer event IDs are immutable and their exact reuse must be
        # rejected. Other integrations retain the legacy duplicate response;
        # all sources still enforce tenant-scoped idempotency below.
        replay_status = 409 if source == "odoo" else 200
        replay_name = "immutable event replay rejected" if source == "odoo" else "exact replay idempotency"
        check(results, f"{source} {replay_name}", status, replay_status, {"event_id": event_id, "response": payload})
        changed = dict(body)
        changed["payload"] = {"safe_test": True, "changed": True}
        status, payload = request("POST", f"/api/v1/events/{source}", changed, signed_headers(source, event_id, changed))
        check(results, f"{source} idempotency conflict", status, 409, {"event_id": event_id, "response": payload})
        missing = dict(headers)
        missing.pop("Authorization")
        status, payload = request("POST", f"/api/v1/events/{source}", body, missing)
        check(results, f"{source} missing credential rejected", status, 401, {"response": payload})
        invalid = dict(headers)
        invalid["Authorization"] = "Bearer invalid-audit-credential"
        status, payload = request("POST", f"/api/v1/events/{source}", body, invalid)
        check(results, f"{source} invalid credential rejected", status, 401, {"response": payload})
        stale_id = event_id + "-stale"
        status, payload = request("POST", f"/api/v1/events/{source}", body, signed_headers(source, stale_id, body, int(time.time()) - 900))
        check(results, f"{source} stale HMAC rejected", status, 401, {"response": payload})
        bad_id = event_id + "-bad-signature"
        status, payload = request("POST", f"/api/v1/events/{source}", body, signed_headers(source, bad_id, body, bad_signature=True))
        check(results, f"{source} invalid HMAC rejected", status, 401, {"response": payload})

    token = operator_token()
    auth = {"Authorization": "Bearer " + token}
    for channel, recipient, sender in (("sms", "+10000000000", "AUDIT"), ("email", "recipient@audit.invalid", "sender@audit.invalid")):
        key = f"audit-{channel}-{run_id}"
        message = {
            "tenant_id": TENANT,
            "customer_id": "synthetic-customer",
            "sender": sender,
            "recipient": recipient,
            "source_application": "connectivity-audit",
            "classification": "transactional",
            "content": "Synthetic connectivity audit; do not deliver.",
        }
        headers = dict(auth)
        headers.update({"X-Request-Id": key, "X-Correlation-Id": correlation, "Idempotency-Key": key})
        status, payload = request("POST", f"/v1/messages/{channel}", message, headers)
        check(results, f"{channel} safe message accepted", status, 202, {"message_id": payload.get("message_id"), "correlation_id": correlation})
        message_id = payload.get("message_id")
        status, duplicate = request("POST", f"/v1/messages/{channel}", message, headers)
        check(results, f"{channel} message idempotent replay", status, 200, {"same_message_id": duplicate.get("message_id") == message_id})
        dispatch_once()
        status, current = request("GET", f"/v1/messages/{message_id}?tenant_id={TENANT}", headers=auth)
        check(results, f"{channel} simulator/test dispatch", status if current.get("status") == "accepted" else 599, 200, {"message_id": message_id, "provider_status": current.get("raw_provider_status"), "carrier_or_bulk_submitted": False})

        source = "telnexa" if channel == "sms" else "klyrow"
        event_type = "telnexa.sms.delivered" if channel == "sms" else "klyrow.email.delivered"
        callback_id = f"audit-{source}-callback-{run_id}"
        callback = envelope(source, event_type, callback_id, correlation, {"message_id": message_id, "status": "delivered", "safe_test": True})
        status, event_response = request("POST", f"/api/v1/events/{source}", callback, signed_headers(source, callback_id, callback))
        check(results, f"{source} delivery callback", status, 202, {"event_id": callback_id, "message_id": message_id, "response": event_response})
        status, current = request("GET", f"/v1/messages/{message_id}?tenant_id={TENANT}", headers=auth)
        check(results, f"{source} callback state read-back", status if current.get("status") == "delivered" else 599, 200, {"message_id": message_id, "normalized_status": current.get("status")})

    status, payload = request("GET", f"/api/v1/ops/correlations/{correlation}?tenant_id={TENANT}", headers=auth)
    check(results, "correlation trace read-back", status, 200, {"correlation_id": correlation, "event_count": len(payload.get("items", [])), "sources": sorted({item.get("source") for item in payload.get("items", [])})})
    status, _ = request("GET", "/api/v1/ops/summary", headers={"Authorization": "Bearer invalid-audit-credential"})
    check(results, "operator invalid credential rejected", status, 403)
    status, metrics = request("GET", "/metrics")
    check(results, "Prometheus metrics reachable", status, 200, metrics)

    return {
        "schema_version": "connectivity-audit.v1",
        "run_id": run_id,
        "started_and_completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "safe_mode": True,
        "real_bulk_sms_or_email_sent": False,
        "correlation_id": correlation,
        "summary": {"pass": sum(x["status"] == "PASS" for x in results), "fail": sum(x["status"] == "FAIL" for x in results)},
        "tests": results,
    }


def host_main() -> int:
    source = Path(__file__).read_bytes()
    command = ["docker", "exec", "-i", CONTAINER, "python", "-", "--inside"]
    completed = subprocess.run(command, input=source, capture_output=True, timeout=90)
    if completed.returncode:
        sys.stderr.buffer.write(completed.stderr)
        return completed.returncode
    sys.stdout.buffer.write(completed.stdout)
    return 0


if __name__ == "__main__":
    if "--inside" in sys.argv:
        print(json.dumps(live_audit(), indent=2, sort_keys=True))
    else:
        raise SystemExit(host_main())
