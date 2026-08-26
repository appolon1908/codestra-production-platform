"""Production dependencies and durable inbox for the Postal inbound adapter."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from .core import ControlPlaneError, now_iso
from .database import Connection, is_postgres, json_value
from .email_provisioning import CampaignMailboxRegistry
from .postal_inbound import PostalInboundAdapter


INBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS postal_inbound_event(
 provider_event_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,request_hash TEXT NOT NULL,
 correlation_id TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT,error_detail_safe TEXT,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
"""


def _secret(name: str) -> str:
    value = os.getenv(name, "")
    path = os.getenv(name + "_FILE", "")
    if not value and path:
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
    return value


def _secure_url(name: str) -> str:
    value = os.getenv(name, "").rstrip("/")
    if not value:
        raise ControlPlaneError(name.lower() + "_not_configured")
    if not value.startswith("https://") and os.getenv("POSTAL_ALLOW_INSECURE_TEST_ENDPOINTS", "false") != "true":
        raise ControlPlaneError("insecure_dependency_url_denied")
    return value


class ClamdScanner:
    """Minimal clamd INSTREAM client. Any protocol or network error fails closed."""

    def scan(self, content: bytes, *, filename: str, mime_type: str) -> str:
        host = os.getenv("POSTAL_CLAMD_HOST", "")
        port = int(os.getenv("POSTAL_CLAMD_PORT", "3310"))
        if not host:
            raise ControlPlaneError("malware_scanner_not_configured")
        try:
            with socket.create_connection((host, port), timeout=float(os.getenv("POSTAL_DEPENDENCY_TIMEOUT", "5"))) as stream:
                stream.sendall(b"zINSTREAM\0")
                for offset in range(0, len(content), 65536):
                    chunk = content[offset:offset + 65536]
                    stream.sendall(struct.pack("!I", len(chunk)) + chunk)
                stream.sendall(struct.pack("!I", 0))
                response = stream.recv(4096).decode("utf-8", "replace").strip("\0\r\n")
        except OSError as exc:
            raise ControlPlaneError("malware_scanner_unavailable") from exc
        if response.endswith(" OK"):
            return "CLEAN"
        if " FOUND" in response:
            return "MALWARE"
        raise ControlPlaneError("malware_scanner_invalid_response")


class ProtectedHttpObjectStore:
    """Writes opaque objects to a tenant-scoped protected storage API."""

    def _put(self, kind: str, *, tenant_id: str, object_key: str, content: bytes,
             metadata: dict[str, str]) -> str:
        base = _secure_url("POSTAL_OBJECT_STORE_URL")
        token = _secret("POSTAL_OBJECT_STORE_TOKEN")
        if not token:
            raise ControlPlaneError("object_store_credentials_not_configured")
        path = "/".join(urllib.parse.quote(x, safe="") for x in (tenant_id, kind, object_key))
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/octet-stream",
            "X-Object-Metadata": json.dumps(metadata, separators=(",", ":"), sort_keys=True),
            "If-None-Match": "*",
        }
        request = urllib.request.Request(base + "/v1/objects/" + path, content, headers, method="PUT")
        try:
            with urllib.request.urlopen(request, timeout=float(os.getenv("POSTAL_DEPENDENCY_TIMEOUT", "5"))) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 412:
                raise ControlPlaneError("object_store_unavailable") from exc
            result = {"object_reference": f"protected-object://{tenant_id}/{kind}/{object_key}"}
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ControlPlaneError("object_store_unavailable") from exc
        reference = str(result.get("object_reference") or "")
        if not reference or reference.startswith(("http://", "https://")):
            raise ControlPlaneError("object_store_invalid_reference")
        return reference

    def put_clean(self, **value: Any) -> str:
        return self._put("clean", **value)

    def put_quarantine(self, **value: Any) -> str:
        return self._put("quarantine", **value)


class OdooInboundProjection:
    """Projects through an authenticated Odoo HTTP contract and requires read-back."""

    def deliver(self, value: dict[str, Any]) -> dict[str, Any]:
        url = _secure_url("POSTAL_ODOO_INBOUND_URL")
        secret = _secret("POSTAL_ODOO_HMAC_SECRET")
        if not secret:
            raise ControlPlaneError("odoo_inbound_credentials_not_configured")
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        stamp = str(int(time.time()))
        event_id = str(value["provider_event_id"])
        path = urllib.parse.urlsplit(url).path
        canonical = b"\n".join((stamp.encode(), event_id.encode(), b"POST", path.encode(), raw))
        signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json", "X-Codestra-Timestamp": stamp,
            "X-Codestra-Event-ID": event_id, "X-Codestra-Signature": signature,
            "X-Tenant-ID": str(value["tenant_id"]),
            "X-Correlation-ID": str(value["correlation_id"]),
            "Idempotency-Key": "postal-inbound:" + event_id,
        }
        try:
            with urllib.request.urlopen(urllib.request.Request(url, raw, headers, method="POST"),
                                        timeout=float(os.getenv("POSTAL_DEPENDENCY_TIMEOUT", "5"))) as response:
                if response.status not in (200, 201):
                    raise ControlPlaneError("odoo_inbound_projection_failed")
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise ControlPlaneError("odoo_inbound_projection_failed") from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ControlPlaneError("odoo_inbound_unavailable") from exc
        return result


class PostalInbox:
    def __init__(self, path: str):
        self.path = path
        if not is_postgres():
            with Connection(path) as db:
                db.executescript(INBOX_SCHEMA)

    def _tenant(self, db: Connection, tenant_id: str) -> None:
        if is_postgres():
            db.execute("SELECT set_config('app.tenant_id', ?, true)", (tenant_id,))

    def run(self, *, tenant_id: str, provider_event_id: str, correlation_id: str,
            recipient: str, raw_message: bytes, adapter: PostalInboundAdapter) -> tuple[dict[str, Any], bool]:
        request_hash = hashlib.sha256(b"\0".join((tenant_id.encode(), recipient.lower().encode(), raw_message))).hexdigest()
        stamp = now_iso()
        with Connection(self.path) as db:
            self._tenant(db, tenant_id)
            lock = " FOR UPDATE" if is_postgres() else ""
            row = db.execute("SELECT * FROM postal_inbound_event WHERE provider_event_id=?" + lock, (provider_event_id,)).fetchone()
            if row:
                if row["tenant_id"] != tenant_id or row["request_hash"] != request_hash:
                    raise ControlPlaneError("inbound_idempotency_conflict")
                if row["status"] == "COMPLETED":
                    result = row["result_json"]
                    return (result if isinstance(result, dict) else json.loads(result)), True
                if row["status"] == "PROCESSING":
                    updated = row["updated_at"]
                    if isinstance(updated, str):
                        updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    lease = timedelta(seconds=int(os.getenv("POSTAL_PROCESSING_LEASE_SECONDS", "300")))
                    if datetime.now(timezone.utc) - updated <= lease:
                        raise ControlPlaneError("inbound_processing")
                db.execute("UPDATE postal_inbound_event SET status='PROCESSING',error_detail_safe=NULL,updated_at=? WHERE provider_event_id=?", (stamp, provider_event_id))
            else:
                db.execute("INSERT INTO postal_inbound_event(provider_event_id,tenant_id,request_hash,correlation_id,status,result_json,error_detail_safe,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (provider_event_id, tenant_id, request_hash, correlation_id, "PROCESSING", None, None, stamp, stamp))
        try:
            result = adapter.ingest(tenant_id=tenant_id, recipient=recipient, raw_message=raw_message,
                                    correlation_id=correlation_id, provider_event_id=provider_event_id)
        except Exception as exc:
            safe = str(exc)[:160] if isinstance(exc, ControlPlaneError) else "inbound_processing_failed"
            with Connection(self.path) as db:
                self._tenant(db, tenant_id)
                db.execute("UPDATE postal_inbound_event SET status='FAILED',error_detail_safe=?,updated_at=? WHERE provider_event_id=?", (safe, now_iso(), provider_event_id))
            raise
        encoded = json_value(result)
        with Connection(self.path) as db:
            self._tenant(db, tenant_id)
            db.execute("UPDATE postal_inbound_event SET status='COMPLETED',result_json=?,updated_at=? WHERE provider_event_id=?", (encoded, now_iso(), provider_event_id))
        return result, False


def production_adapter(path: str) -> PostalInboundAdapter:
    return PostalInboundAdapter(CampaignMailboxRegistry(path), ClamdScanner(),
                                ProtectedHttpObjectStore(), OdooInboundProjection())
