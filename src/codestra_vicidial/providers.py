"""Staging-only provider contracts and deterministic mocks."""
from __future__ import annotations

from dataclasses import dataclass, field

from .communications import MessageState, OutboundMessage


class ProviderUnavailable(RuntimeError):
    pass


@dataclass
class MockProvider:
    name: str
    healthy: bool = True
    sent: dict[str, OutboundMessage] = field(default_factory=dict)

    def health_check(self) -> bool:
        return self.healthy

    def send_approved(self, message: OutboundMessage) -> str:
        if not self.healthy:
            raise ProviderUnavailable(f"{self.name} unavailable")
        if message.state not in {MessageState.APPROVED, MessageState.QUEUED}:
            raise PermissionError("message is not approved")
        reference = f"mock:{self.name}:{message.message_id}"
        self.sent.setdefault(reference, message)
        return reference

    def read_delivery_status(self, provider_reference: str) -> MessageState:
        if not self.healthy:
            raise ProviderUnavailable(f"{self.name} unavailable")
        if provider_reference not in self.sent:
            raise KeyError("provider reference not found")
        return MessageState.SENT


class EmailProvider(MockProvider):
    def read_messages(self) -> list[dict]:
        return []

    def create_draft(self, message: OutboundMessage) -> OutboundMessage:
        if message.state is not MessageState.DRAFT:
            raise ValueError("email draft must be DRAFT")
        return message

    def read_bounce_status(self, provider_reference: str) -> MessageState:
        return self.read_delivery_status(provider_reference)

    def read_complaint_status(self, provider_reference: str) -> MessageState:
        return self.read_delivery_status(provider_reference)


class SMSProvider(MockProvider):
    pass


class WhatsAppProvider(MockProvider):
    pass


class SocialProvider(MockProvider):
    def receive_message(self) -> list[dict]:
        return []

    def read_thread(self, _thread_reference: str) -> list[dict]:
        return []

    def read_profile_reference(self, subject: str) -> str:
        return f"profile:{self.name}:{subject}"


class MeetingProvider(MockProvider):
    def schedule(self, meeting_reference: str) -> dict:
        if not self.healthy:
            raise ProviderUnavailable(f"{self.name} unavailable")
        return {"meeting_reference": meeting_reference, "status": "STAGING"}

