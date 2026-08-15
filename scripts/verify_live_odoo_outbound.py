"""Run with Odoo shell to verify signed Odoo -> Middleware synthetic events."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid


params = env["ir.config_parameter"].sudo()
target = params.get_param("codestra.middleware.event_url")
api_key = params.get_param("codestra.middleware.api_key")
secret = params.get_param("codestra.middleware.webhook_secret")
tenant = params.get_param("codestra.middleware.tenant_id")
assert all((target, api_key, secret, tenant))


def send(event_id, idem, correlation, *, bearer=api_key, signing_secret=secret):
    envelope = {
        "event_type": "customer.updated", "event_version": "1.0",
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tenant_id": tenant, "customer_id": "CODESTRA-INTEGRATION-TEST-" + correlation,
        "correlation_id": correlation, "idempotency_key": idem,
        "payload": {"synthetic_test": True, "tag": "CODESTRA-INTEGRATION-TEST-" + correlation},
        "metadata": {"source": "odoo", "synthetic_test": True},
    }
    raw = json.dumps(envelope, separators=(",", ":")).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(signing_secret.encode(), b"\n".join(
        (stamp.encode(), event_id.encode(), b"odoo", raw)), hashlib.sha256).hexdigest()
    request = urllib.request.Request(target, raw, {
        "Content-Type": "application/json", "Authorization": "Bearer " + bearer,
        "X-Event-Id": event_id, "X-Timestamp": stamp, "X-Signature": "sha256=" + signature,
    }, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


stamp = uuid.uuid4().hex
correlation = "odoo-outbound-live-" + stamp
idem = "odoo-outbound-idem-" + stamp
event_id = "odoo-live-" + stamp
status, accepted = send(event_id, idem, correlation)
assert status == 202 and accepted["correlation_id"] == correlation
status_replay, replay = send(event_id, idem, correlation)
assert status_replay == 409 and replay["error"] == "replayed_event_id"
status_retry, retry = send("odoo-retry-" + stamp, idem, correlation)
assert status_retry == 200 and retry["duplicate"] is True
status_bearer, bad_bearer = send("odoo-bad-bearer-" + stamp, "bad-bearer-" + idem,
                                 correlation, bearer="invalid")
assert status_bearer == 401 and bad_bearer["error"] == "invalid_api_key"
status_hmac, bad_hmac = send("odoo-bad-hmac-" + stamp, "bad-hmac-" + idem,
                             correlation, signing_secret="invalid")
assert status_hmac == 401 and bad_hmac["error"] == "invalid_signature"
event = env["codestra.integration.event"].register_event(
    "customer.updated", "odoo", "middleware", {"synthetic_test": True, "tag": stamp},
    correlation_id=correlation, idempotency_key=idem,
)
env["codestra.integration.audit"]._append(
    event, "middleware.delivery", "success", {"http_status": status, "event_id": event_id},
)
env.cr.commit()
print(json.dumps({
    "correlation_id": correlation, "accepted": status, "replay_rejection": status_replay,
    "idempotent_retry": status_retry, "invalid_bearer": status_bearer,
    "invalid_hmac": status_hmac, "odoo_event_id": event.id,
}, sort_keys=True))
