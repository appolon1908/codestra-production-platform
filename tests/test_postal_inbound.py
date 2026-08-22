from email.message import EmailMessage

import pytest

from control_plane_service.core import ControlPlaneError
from control_plane_service.postal_inbound import PostalInboundAdapter, sanitize_filename


class Router:
    def route_inbound(self, recipient, tenant_id=None):
        if recipient.lower() != "maria@codestra.co":
            raise ControlPlaneError("inbound_recipient_not_found")
        return {"tenant_id": "COD", "campaign_id": "campaign-1", "agent_id": "agent-1",
                "mailbox_id": "mailbox-1"}


class Scanner:
    def __init__(self, result="CLEAN"):
        self.result = result
        self.calls = []
    def scan(self, content, **metadata):
        self.calls.append((content, metadata))
        return self.result


class Storage:
    def __init__(self):
        self.clean = []
        self.quarantine = []
    def put_clean(self, **value):
        self.clean.append(value)
        return "tenant-object://clean/1"
    def put_quarantine(self, **value):
        self.quarantine.append(value)
        return "tenant-object://quarantine/1"


class Projection:
    def __init__(self): self.values = []
    def deliver(self, value):
        self.values.append(value)
        return value


def message(filename="report.pdf", mime="application/pdf"):
    value = EmailMessage()
    value["From"] = "internal@klyrow.test"
    value["To"] = "maria@codestra.co"
    value["Subject"] = "Internal canary"
    value["Message-ID"] = "<canary-1@klyrow.test>"
    value["In-Reply-To"] = "<parent@klyrow.test>"
    value["References"] = "<root@klyrow.test> <parent@klyrow.test>"
    value.set_content("controlled message")
    major, minor = mime.split("/", 1)
    value.add_attachment(b"safe fixture", maintype=major, subtype=minor, filename=filename)
    return value.as_bytes()


def adapter(scanner=None, storage=None, projection=None):
    return PostalInboundAdapter(Router(), scanner or Scanner(), storage or Storage(), projection or Projection())


def test_exact_inbound_preserves_threading_and_delivers_only_scanned_attachment():
    scanner, storage, projection = Scanner(), Storage(), Projection()
    result = adapter(scanner, storage, projection).ingest(
        tenant_id="COD", recipient="maria@codestra.co", raw_message=message(),
        correlation_id="correlation-1", provider_event_id="postal-event-1")
    assert result["message_id"] == "<canary-1@klyrow.test>"
    assert result["in_reply_to"] == "<parent@klyrow.test>"
    assert result["references"] == ["<root@klyrow.test>", "<parent@klyrow.test>"]
    assert scanner.calls and storage.clean and not storage.quarantine
    assert projection.values[0]["attachments"][0]["scan_result"] == "CLEAN"
    assert projection.values[0]["attachments"][0]["object_reference"]


@pytest.mark.parametrize("recipient", ["unknown@codestra.co", "random@codestra.co"])
def test_unknown_recipient_has_no_route(recipient):
    with pytest.raises(ControlPlaneError, match="inbound_recipient_not_found"):
        adapter().ingest(tenant_id="COD", recipient=recipient, raw_message=message(),
                         correlation_id="correlation-1", provider_event_id="postal-event-1")


def test_malware_is_quarantined_and_never_projected():
    storage, projection = Storage(), Projection()
    with pytest.raises(ControlPlaneError, match="attachment_quarantined"):
        adapter(Scanner("INFECTED"), storage, projection).ingest(
            tenant_id="COD", recipient="maria@codestra.co", raw_message=message(),
            correlation_id="correlation-1", provider_event_id="postal-event-1")
    assert storage.quarantine and not storage.clean and not projection.values


@pytest.mark.parametrize(("filename", "mime", "error"), [
    ("payload.exe", "application/pdf", "attachment_executable_denied"),
    ("archive.zip", "application/zip", "attachment_mime_denied"),
])
def test_dangerous_attachment_is_denied_before_storage(filename, mime, error):
    with pytest.raises(ControlPlaneError, match=error):
        adapter().ingest(tenant_id="COD", recipient="maria@codestra.co",
                         raw_message=message(filename, mime), correlation_id="correlation-1",
                         provider_event_id="postal-event-1")


def test_filename_is_basename_sanitized():
    assert sanitize_filename("../../Résumé 2026.pdf") == "Resume 2026.pdf"
