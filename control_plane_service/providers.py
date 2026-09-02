from __future__ import annotations

import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    provider_message_id: str
    status: str
    raw_status: str


_token_cache: tuple[str, float] | None = None


def _secret(path_variable: str) -> str:
    path = os.getenv(path_variable, "")
    if not path:
        raise ProviderError("provider_credentials_missing")
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProviderError("provider_credentials_unavailable") from exc
    if not value:
        raise ProviderError("provider_credentials_missing")
    return value


def _klyrow_token() -> str:
    global _token_cache
    now = time.time()
    if _token_cache and _token_cache[1] > now + 15:
        return _token_cache[0]
    token_url = os.getenv("KLYROW_OIDC_TOKEN_URL", "")
    if token_url != "https://auth.codestra.co/realms/codestra/protocol/openid-connect/token":
        raise ProviderError("unapproved_oidc_issuer")
    client_id = os.getenv("KLYROW_OIDC_CLIENT_ID", "")
    if client_id != "cod-web-out-email-production":
        raise ProviderError("unapproved_oidc_client")
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": _secret("KLYROW_OIDC_CLIENT_SECRET_FILE"),
        }
    ).encode()
    request = urllib.request.Request(
        token_url,
        body,
        {"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.loads(response.read())
    token = str(result.get("access_token") or "")
    expires_in = min(int(result.get("expires_in") or 60), 300)
    if not token:
        raise ProviderError("provider_token_missing")
    _token_cache = (token, now + expires_in)
    return token


def _klyrow_tls_context() -> ssl.SSLContext:
    ca = os.getenv("KLYROW_MTLS_CA_FILE", "")
    cert = os.getenv("KLYROW_MTLS_CERT_FILE", "")
    key = os.getenv("KLYROW_MTLS_KEY_FILE", "")
    if not all((ca, cert, key)):
        raise ProviderError("provider_mtls_configuration_missing")
    context = ssl.create_default_context(cafile=ca)
    context.load_cert_chain(certfile=cert, keyfile=key)
    return context


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
    if host not in {
        "10.40.0.2",
        "10.40.0.4",
        "localhost",
        "127.0.0.1",
        "telnexa.internal.codestra.agency",
    }:
        raise ProviderError("provider_url_not_private")
    return url


def _telnexa_submit(message: dict[str, object]) -> ProviderResult:
    """Submit one SMS through the private gateway's exact authenticated contract."""

    url = _private_url("TELNEXA")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.path != "/v1/messages"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ProviderError("provider_url_not_approved")
    try:
        content = json.loads(str(message.get("content_payload") or "{}"))
    except json.JSONDecodeError as exc:
        raise ProviderError("provider_payload_invalid") from exc
    if not isinstance(content, dict):
        raise ProviderError("provider_payload_invalid")
    body_value = content.get("text", content.get("content"))
    if not isinstance(body_value, str) or not body_value.strip():
        raise ProviderError("provider_payload_invalid")
    provider_attempt = int(message.get("provider_attempt") or 0)
    caller_idempotency_key = str(message["idempotency_key"])
    provider_idempotency_key = caller_idempotency_key
    if provider_attempt > 0:
        attempt_identity = "\n".join(
            (
                str(message["tenant_id"]),
                str(message["message_id"]),
                caller_idempotency_key,
                str(provider_attempt),
            )
        )
        provider_idempotency_key = (
            "retry-" + hashlib.sha256(attempt_identity.encode()).hexdigest()
        )
    payload = {
        "body": body_value,
        "correlation_id": str(message["correlation_id"]),
        "customer_id": str(message["customer_id"]),
        "idempotency_key": provider_idempotency_key,
        "message_id": str(message["message_id"]),
        "sender": str(message["sender"]),
        "tenant_id": str(message["tenant_id"]),
        "to": str(message["normalized_destination"]),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = hmac.new(
        _secret("TELNEXA_OUTBOUND_HMAC_SECRET_FILE").encode(),
        b"POST\n/v1/messages\n"
        + timestamp.encode()
        + b"\n"
        + nonce.encode()
        + b"\n"
        + raw,
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        url,
        raw,
        {
            "Authorization": "Bearer " + _secret("TELNEXA_OUTBOUND_API_KEY_FILE"),
            "Content-Type": "application/json",
            "X-Codestra-Nonce": nonce,
            "X-Codestra-Signature": "sha256=" + signature,
            "X-Codestra-Timestamp": timestamp,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=float(os.getenv("CONTROL_PLANE_HTTP_TIMEOUT", "5"))
        ) as response:
            if response.status != 202:
                raise ProviderError("provider_response_invalid")
            response_raw = response.read(2049)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError("provider_unavailable") from exc
    if not response_raw or len(response_raw) > 2048:
        raise ProviderError("provider_response_invalid")
    try:
        result = json.loads(response_raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderError("provider_response_invalid") from exc
    if not isinstance(result, dict):
        raise ProviderError("provider_response_invalid")
    adapter_message_id = result.get("adapter_message_id")
    state = result.get("state")
    duplicate = result.get("duplicate")
    carrier_submitted = result.get("carrier_submitted")
    accepted = result.get("accepted")
    try:
        uuid.UUID(str(adapter_message_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProviderError("provider_response_invalid") from exc
    if accepted is not True or not isinstance(duplicate, bool):
        raise ProviderError("provider_response_invalid")
    if state == "submitted" and carrier_submitted is True:
        return ProviderResult(str(adapter_message_id), "accepted", "submitted")
    if state == "rejected" and carrier_submitted is False:
        return ProviderResult(str(adapter_message_id), "rejected", "rejected")
    if state == "outcome_unknown" and carrier_submitted is False:
        return ProviderResult(str(adapter_message_id), "deferred", "outcome_unknown")
    if duplicate is True and state == "submitting" and carrier_submitted is False:
        return ProviderResult(str(adapter_message_id), "deferred", "submitting")
    # A safe-mode receipt is not evidence of carrier acceptance. The worker's
    # production ledger must therefore stay fail-closed until the gateway's
    # independently reviewed delivery gates are also enabled.
    if state == "mock_accepted" and carrier_submitted is False:
        raise ProviderError("provider_delivery_not_authorized")
    raise ProviderError("provider_response_invalid")


def submit(message: dict[str, object]) -> ProviderResult:
    provider = str(message["provider"])
    mode = os.getenv(provider.upper() + "_MODE", "simulator" if provider == "telnexa" else "test")
    if provider == "telnexa" and mode == "simulator":
        return ProviderResult("sim-" + str(uuid.uuid4()), "accepted", "simulator_accepted")
    if provider == "klyrow" and mode in {"test", "safe"}:
        return ProviderResult("test-" + str(uuid.uuid4()), "accepted", "test_accepted")
    if mode != "production" or os.getenv("CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED", "false") != "true":
        raise ProviderError("production_delivery_not_authorized")
    if provider == "telnexa":
        return _telnexa_submit(message)
    url = _private_url(provider.upper())
    campaign = str(message.get("campaign_id") or "")
    allowed_campaign = os.getenv("KLYROW_ALLOWED_CAMPAIGN", "")
    if campaign != "COD-WEB-OUT" or allowed_campaign != campaign:
        raise ProviderError("provider_campaign_not_authorized")
    content = json.loads(str(message.get("content_payload") or "{}"))
    payload = {
        "to": str(message["normalized_destination"]),
        "sender": str(message["sender"]),
        "reply_to": str(content.get("reply_to") or "support@codestra.co"),
        "subject": str(content.get("subject") or ""),
        "html": str(content.get("html") or content.get("content") or ""),
        "text": str(content.get("text") or content.get("content") or ""),
        "template_id": content.get("template_id"),
        "campaign_id": campaign,
        "stream": str(message["classification"]),
    }
    request = urllib.request.Request(
        url,
        json.dumps(payload, separators=(",", ":")).encode(),
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + _klyrow_token(),
            "X-Correlation-Id": str(message["correlation_id"]),
            "X-Codestra-Campaign": campaign,
            "Idempotency-Key": str(message["idempotency_key"]),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5, context=_klyrow_tls_context()) as response:
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
