"""Fail-closed Postal inbound adapter with exact routing and attachment quarantine."""
from __future__ import annotations

import re
import unicodedata
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import PurePath
from typing import Any, Protocol

from .core import ControlPlaneError


ALLOWED_ATTACHMENT_MIME = {
    "application/pdf", "image/gif", "image/jpeg", "image/png", "text/csv",
    "text/plain", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
DENIED_EXTENSIONS = {
    ".app", ".bat", ".bin", ".cmd", ".com", ".dll", ".dmg", ".exe", ".hta",
    ".iso", ".jar", ".js", ".lnk", ".msi", ".ps1", ".scr", ".sh", ".vbs",
}
MAX_MESSAGE_BYTES = 26_214_400
MAX_ATTACHMENT_BYTES = 10_485_760
MAX_TOTAL_ATTACHMENT_BYTES = 20_971_520
MAX_ATTACHMENTS = 20


class ExactRouter(Protocol):
    def route_inbound(self, recipient: str) -> dict[str, Any]: ...


class MalwareScanner(Protocol):
    def scan(self, content: bytes, *, filename: str, mime_type: str) -> str: ...


class TenantObjectStore(Protocol):
    def put_clean(self, *, tenant_id: str, object_key: str, content: bytes,
                  metadata: dict[str, str]) -> str: ...
    def put_quarantine(self, *, tenant_id: str, object_key: str, content: bytes,
                       metadata: dict[str, str]) -> str: ...


class InboundProjection(Protocol):
    def deliver(self, value: dict[str, Any]) -> dict[str, Any]: ...


def sanitize_filename(value: str | None) -> str:
    original = PurePath((value or "attachment").replace("\\", "/")).name
    normalized = unicodedata.normalize("NFKD", original).encode("ascii", "ignore").decode()
    normalized = normalized.replace("\x00", "")
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", normalized).strip(" .")[:180]
    if not safe or safe in {".", ".."}:
        safe = "attachment"
    if PurePath(safe).suffix.lower() in DENIED_EXTENSIONS:
        raise ControlPlaneError("attachment_executable_denied")
    return safe


class PostalInboundAdapter:
    def __init__(self, router: ExactRouter, scanner: MalwareScanner,
                 storage: TenantObjectStore, projection: InboundProjection):
        self.router, self.scanner = router, scanner
        self.storage, self.projection = storage, projection

    def ingest(self, *, tenant_id: str, recipient: str, raw_message: bytes,
               correlation_id: str, provider_event_id: str) -> dict[str, Any]:
        if not tenant_id or not correlation_id or not provider_event_id:
            raise ControlPlaneError("inbound_metadata_required")
        if not raw_message or len(raw_message) > MAX_MESSAGE_BYTES:
            raise ControlPlaneError("inbound_message_size_denied")
        route = self.router.route_inbound(recipient)
        if route.get("tenant_id") != tenant_id:
            raise ControlPlaneError("inbound_tenant_mismatch")
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        message_id = str(message.get("Message-ID") or "").strip()
        if not message_id:
            raise ControlPlaneError("inbound_message_id_required")

        pending: list[tuple[str, str, bytes]] = []
        total = 0
        for part in message.iter_attachments():
            if len(pending) >= MAX_ATTACHMENTS:
                raise ControlPlaneError("attachment_count_denied")
            mime_type = part.get_content_type().lower()
            if mime_type not in ALLOWED_ATTACHMENT_MIME:
                raise ControlPlaneError("attachment_mime_denied")
            filename = sanitize_filename(part.get_filename())
            content = part.get_payload(decode=True) or b""
            if not content or len(content) > MAX_ATTACHMENT_BYTES:
                raise ControlPlaneError("attachment_size_denied")
            total += len(content)
            if total > MAX_TOTAL_ATTACHMENT_BYTES:
                raise ControlPlaneError("attachment_total_size_denied")
            pending.append((filename, mime_type, content))

        scan_results = []
        for filename, mime_type, content in pending:
            result = str(self.scanner.scan(content, filename=filename, mime_type=mime_type)).upper()
            scan_results.append(result)
            if result != "CLEAN":
                self.storage.put_quarantine(
                    tenant_id=tenant_id,
                    object_key=f"quarantine/{uuid.uuid4()}/{filename}", content=content,
                    metadata={"scan_result": result, "provider_event_id": provider_event_id,
                              "correlation_id": correlation_id, "mime_type": mime_type},
                )
                raise ControlPlaneError("attachment_quarantined")

        attachments = []
        for (filename, mime_type, content), scan_result in zip(pending, scan_results):
            reference = self.storage.put_clean(
                tenant_id=tenant_id,
                object_key=f"messages/{uuid.uuid4()}/{filename}", content=content,
                metadata={"scan_result": scan_result, "provider_event_id": provider_event_id,
                          "correlation_id": correlation_id, "mime_type": mime_type},
            )
            attachments.append({"filename": filename, "mime_type": mime_type,
                                "size": len(content), "object_reference": reference,
                                "scan_result": scan_result})

        projection = {
            "tenant_id": tenant_id, "campaign_id": route["campaign_id"],
            "agent_id": route["agent_id"], "mailbox_id": route["mailbox_id"],
            "recipient": recipient.strip().lower(), "message_id": message_id,
            "in_reply_to": str(message.get("In-Reply-To") or "").strip() or None,
            "references": str(message.get("References") or "").split(),
            "correlation_id": correlation_id, "provider_event_id": provider_event_id,
            "subject": str(message.get("Subject") or ""), "attachments": attachments,
        }
        readback = self.projection.deliver(projection)
        required = ("tenant_id", "campaign_id", "agent_id", "mailbox_id", "message_id", "correlation_id")
        if any(readback.get(key) != projection[key] for key in required):
            raise ControlPlaneError("inbound_projection_readback_mismatch")
        return projection
