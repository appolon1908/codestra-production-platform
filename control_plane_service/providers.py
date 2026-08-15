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


def _request_json(method: str, url: str, payload: dict[str, object] | None, headers: dict[str, str]) -> dict[str, object]:
    raw = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    values = {"Accept": "application/json", **headers}
    if raw is not None:
        values["Content-Type"] = "application/json"
    request = urllib.request.Request(url, raw, values, method=method)
    with urllib.request.urlopen(request, timeout=float(os.getenv("CONTROL_PLANE_HTTP_TIMEOUT", "5"))) as response:
        return json.loads(response.read() or b"{}")


def _private_url(name: str) -> str:
    url = os.getenv(name + "_URL", "")
    if not url:
        raise ProviderError("provider_url_missing")
    host = urllib.parse.urlparse(url).hostname
    if host not in {"10.40.0.2", "10.40.0.4", "localhost", "127.0.0.1"}:
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


def submit_crawler(job: dict[str, object]) -> ProviderResult:
    mode = os.getenv("KYQRA_MODE", "test")
    if mode in {"test", "safe", "simulator"}:
        return ProviderResult("test-job-" + str(uuid.uuid4()), "accepted", "test_accepted")
    if mode not in {"private_safe", "production"}:
        raise ProviderError("production_delivery_not_authorized")
    if mode == "production" and os.getenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED", "false") != "true":
        raise ProviderError("production_delivery_not_authorized")
    url = _private_url("KYQRA")
    token = os.getenv("KYQRA_OUTBOUND_API_KEY", "")
    if not token:
        raise ProviderError("provider_credentials_missing")
    payload = {
        "startUrls": [job["target_url"]], "mode": "single", "maxPages": 1,
        "maxDepth": 0, "browser": "http", "extract": [],
        "includePatterns": [], "excludePatterns": [], "requestsPerSecond": 0.1,
    }
    request = urllib.request.Request(url, json.dumps(payload).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + token,
        "X-Correlation-Id": str(job["correlation_id"]), "X-Tenant-Id": str(job["tenant_id"]),
        "Idempotency-Key": str(job["idempotency_key"]),
    }, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.loads(response.read())
    return ProviderResult(str(result["id"]), "accepted", str(result.get("status", "accepted")))


def crawler_action(action: str, job: dict[str, object]) -> dict[str, object]:
    """Call only Kyqra's authenticated API; safe mode remains fully local."""
    if action not in {"status", "results", "cancel", "retry"}:
        raise ProviderError("unsupported_crawler_action")
    mode = os.getenv("KYQRA_MODE", "test")
    if mode in {"test", "safe", "simulator"}:
        states = {"status": "completed", "results": "completed", "cancel": "cancelled", "retry": "accepted"}
        result: dict[str, object] = {"id": job.get("provider_job_id"), "status": states[action], "safe_test": True}
        if action == "results":
            result["items"] = [{"url": job["target_url"], "title": "Codestra connectivity test", "test_record": True}]
        return result
    if mode not in {"private_safe", "production"}:
        raise ProviderError("production_delivery_not_authorized")
    if mode == "production" and os.getenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED", "false") != "true":
        raise ProviderError("production_delivery_not_authorized")
    base = _private_url("KYQRA").rstrip("/")
    provider_id = urllib.parse.quote(str(job.get("provider_job_id") or ""), safe="")
    token = os.getenv("KYQRA_OUTBOUND_API_KEY", "")
    if not provider_id or not token:
        raise ProviderError("provider_credentials_missing")
    suffix = {"status": "", "results": "/results", "cancel": "/cancel", "retry": "/retry"}[action]
    method = "GET" if action in {"status", "results"} else "POST"
    headers = {"Authorization": "Bearer " + token, "X-Correlation-Id": str(job["correlation_id"]),
               "X-Tenant-Id": str(job["tenant_id"]), "X-Request-Id": str(job["job_id"]),
               "Idempotency-Key": str(job["idempotency_key"]) + ":" + action}
    result = _request_json(method, f"{base}/{provider_id}{suffix}", {} if method == "POST" else None, headers)
    if action == "results" and "results" in result:
        result["items"] = [row.get("data", {}) for row in result.get("results", []) if isinstance(row, dict)]
    return result
