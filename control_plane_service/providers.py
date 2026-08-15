from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    provider_message_id: str
    status: str
    raw_status: str


def _private_url(name: str) -> str:
    url = os.getenv(name + "_URL", "")
    if not url:
        raise ProviderError("provider_url_missing")
    host = urllib.parse.urlparse(url).hostname
    if host not in {"10.40.0.2", "localhost", "127.0.0.1"}:
        raise ProviderError("provider_url_not_private")
    return url


def submit(message: dict[str, object]) -> ProviderResult:
    provider = str(message["provider"])
    mode = os.getenv(provider.upper() + "_MODE", "simulator" if provider == "telnexa" else "test")
    if provider == "telnexa" and mode == "simulator":
        return ProviderResult("sim-" + str(uuid.uuid4()), "accepted", "simulator_accepted")
    if provider == "klyrow" and mode in {"test", "safe"}:
        return ProviderResult("test-" + str(uuid.uuid4()), "accepted", "test_accepted")
    if mode != "production" or os.getenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED", "false") != "true":
        raise ProviderError("production_delivery_not_authorized")
    url = _private_url(provider.upper())
    token = os.getenv(provider.upper() + "_OUTBOUND_API_KEY", "")
    if not token:
        raise ProviderError("provider_credentials_missing")
    payload = {k: message[k] for k in ("message_id", "tenant_id", "customer_id", "correlation_id", "idempotency_key", "sender", "normalized_destination", "classification")}
    payload["content"] = json.loads(str(message.get("content_payload") or "{}"))
    request = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type":"application/json", "Authorization":"Bearer " + token, "X-Correlation-Id":str(message["correlation_id"]), "Idempotency-Key":str(message["idempotency_key"])}, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.loads(response.read())
    return ProviderResult(str(result["id"]), "accepted", str(result.get("status", "accepted")))
