from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from .core import ControlPlaneError, Store, now_iso

CREATE_FIELDS = {"name", "contact_name", "email", "phone", "company_name", "source", "campaign", "description", "customer_reference"}
PATCH_FIELDS = {"name", "contact_name", "email", "phone", "company_name", "source", "campaign", "description"}
ACTIVITY_FIELDS = {"lead_external_id", "activity_type", "summary", "note", "due_date"}


class OdooCrmClient:
    def __init__(self) -> None:
        self.base = os.getenv("CRM_ODOO_URL", os.getenv("ODOO_BASE_URL", "")).rstrip("/")
        self.secret = os.getenv("CRM_ODOO_HMAC_SECRET", os.getenv("ODOO_OUTBOUND_HMAC_SECRET", ""))
        self.tenant = ""

    def request(self, method: str, path: str, payload: dict[str, Any], tenant: str,
                correlation: str, idempotency: str, retries: int = 2) -> tuple[int, dict[str, Any]]:
        if not self.base or not self.secret: raise ControlPlaneError("crm_odoo_not_configured")
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() if payload else b""
        event_id = "crm-" + uuid.uuid4().hex
        target_path = "/codestra/middleware/v1/crm" + path
        target = self.base + target_path
        for attempt in range(retries + 1):
            stamp = str(int(time.time()))
            canonical = b"\n".join((stamp.encode(), event_id.encode(), method.encode(), target_path.encode(), raw))
            signature = hmac.new(self.secret.encode(), canonical, hashlib.sha256).hexdigest()
            headers = {
                "Content-Type": "application/json", "X-Codestra-Timestamp": stamp,
                "X-Codestra-Event-ID": event_id, "X-Codestra-Signature": signature,
                "X-Tenant-ID": tenant, "X-Correlation-ID": correlation,
                "Idempotency-Key": idempotency,
            }
            try:
                with urllib.request.urlopen(urllib.request.Request(target, raw, headers, method=method), timeout=5) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as exc:
                raw_error = exc.read()
                try: body = json.loads(raw_error or b"{}")
                except (json.JSONDecodeError, UnicodeDecodeError): body = {"error": "odoo_request_failed"}
                if exc.code < 500 or attempt == retries: return exc.code, body
            except (TimeoutError, urllib.error.URLError):
                if attempt == retries: raise ControlPlaneError("odoo_unavailable")
            time.sleep(0.2 * (2 ** attempt))
        raise ControlPlaneError("odoo_unavailable")


class CrmService:
    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def correlation(headers: Any) -> str:
        return headers.get("X-Correlation-ID") or str(uuid.uuid4())

    @staticmethod
    def validate_fields(payload: dict[str, Any], allowed: set[str]) -> None:
        unsupported = sorted(set(payload) - allowed)
        if unsupported: raise ControlPlaneError("unsupported_fields:" + ",".join(unsupported))

    def account(self, customer: dict[str, Any]) -> dict[str, Any]:
        return {"customer_id": customer["customer_id"], "status": "active",
                "company": customer["company_label"], "business_unit": customer["business_unit_label"],
                "permissions": ["lead.create", "lead.read", "lead.update", "activity.create"]}

    def call(self, customer: dict[str, Any], method: str, path: str, payload: dict[str, Any],
             correlation: str, idempotency: str) -> tuple[int, dict[str, Any]]:
        return OdooCrmClient().request(method, path, payload, customer["customer_id"], correlation, idempotency)

    def emit(self, customer: dict[str, Any], event_type: str, external_id: str, correlation: str) -> None:
        event_id = "crm-event-" + uuid.uuid4().hex
        self.store.ingest({"event_id": event_id, "source": "crm", "event_type": event_type,
            "event_version": "1.0", "occurred_at": now_iso(), "tenant_id": customer["customer_id"],
            "customer_id": customer["customer_id"], "correlation_id": correlation,
            "idempotency_key": event_id, "payload": {"external_id": external_id}, "metadata": {}})


def request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
