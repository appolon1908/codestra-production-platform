"""Provider-neutral unified communications staging domain.

This module deliberately contains no provider credentials or delivery client.
Middleware may compose it with approved adapters; the VICIdial host uses only
the VOICE channel and operational-event boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Channel(StrEnum):
    VOICE = "VOICE"
    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"
    FACEBOOK_MESSENGER = "FACEBOOK_MESSENGER"
    INSTAGRAM_DIRECT = "INSTAGRAM_DIRECT"
    TELEGRAM = "TELEGRAM"
    WEB_CHAT = "WEB_CHAT"
    INTERNAL_CHAT = "INTERNAL_CHAT"
    VIDEO_MEETING = "VIDEO_MEETING"
    PUSH_NOTIFICATION = "PUSH_NOTIFICATION"


class ConversationStatus(StrEnum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    WAITING_ON_CUSTOMER = "WAITING_ON_CUSTOMER"
    WAITING_ON_INTERNAL_TEAM = "WAITING_ON_INTERNAL_TEAM"
    ESCALATED = "ESCALATED"
    SLA_WARNING = "SLA_WARNING"
    SLA_BREACHED = "SLA_BREACHED"
    CLOSED = "CLOSED"
    SPAM = "SPAM"
    BLOCKED = "BLOCKED"


class MessageState(StrEnum):
    DRAFT = "DRAFT"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    BOUNCED = "BOUNCED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class ConsentState(StrEnum):
    UNKNOWN = "UNKNOWN"
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    NOT_REQUIRED = "NOT_REQUIRED"


class IdentityResult(StrEnum):
    MATCHED = "MATCHED"
    PROBABLE_MATCH = "PROBABLE_MATCH"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
    NO_MATCH = "NO_MATCH"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class RoutingOutcome(StrEnum):
    ASSIGN_HUMAN = "ASSIGN_HUMAN"
    ASSIGN_AI = "ASSIGN_AI"
    ASSIGN_TEAM = "ASSIGN_TEAM"
    QUEUE = "QUEUE"
    ESCALATE = "ESCALATE"
    SCHEDULE_CALLBACK = "SCHEDULE_CALLBACK"
    REJECT = "REJECT"
    BLOCK = "BLOCK"


class Conversation(StrictModel):
    conversation_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    workspace_id: str
    customer_reference: str | None = None
    channel: Channel
    channel_account: str
    assigned_department: str | None = None
    assigned_agent: str | None = None
    assigned_ai_employee: str | None = None
    status: ConversationStatus = ConversationStatus.UNASSIGNED
    priority: int = Field(default=3, ge=1, le=5)
    language: str = "und"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_assignment_scope(self):
        assignments = [self.assigned_agent, self.assigned_ai_employee]
        if sum(value is not None for value in assignments) > 1:
            raise ValueError("conversation cannot be assigned to human and AI simultaneously")
        if self.status == ConversationStatus.CLOSED and self.closed_at is None:
            raise ValueError("closed conversation requires closed_at")
        return self


class Consent(StrictModel):
    tenant_id: str
    workspace_id: str
    channel: Channel
    purpose: str
    customer_reference: str
    consent_state: ConsentState
    source: str
    effective_at: datetime
    expires_at: datetime | None = None
    withdrawn_at: datetime | None = None
    evidence_reference: str


class OutboundMessage(StrictModel):
    message_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    tenant_id: str
    workspace_id: str
    channel: Channel
    sender_account: str
    recipient_reference: str
    purpose: str
    body: str = Field(min_length=1, max_length=10000)
    state: MessageState = MessageState.DRAFT
    idempotency_key: str = Field(min_length=8, max_length=200)
    template_reference: str | None = None
    approval_reference: str | None = None
    consent_state: ConsentState
    opt_out: bool = False

    @model_validator(mode="after")
    def enforce_governance(self):
        if self.opt_out or self.consent_state in {
            ConsentState.DENIED, ConsentState.WITHDRAWN, ConsentState.EXPIRED
        }:
            if self.state not in {MessageState.BLOCKED, MessageState.CANCELLED}:
                raise ValueError("opt-out or denied consent requires blocked state")
        if self.state not in {MessageState.DRAFT, MessageState.WAITING_FOR_APPROVAL,
                              MessageState.BLOCKED, MessageState.CANCELLED}:
            if not self.approval_reference:
                raise ValueError("outbound delivery requires approval")
        return self


class IdentityCandidate(StrictModel):
    customer_reference: str
    normalized_phone: str | None = None
    normalized_email: str | None = None
    social_provider: str | None = None
    social_subject: str | None = None


def resolve_identity(query: IdentityCandidate, candidates: list[IdentityCandidate]) -> IdentityResult:
    """Only exact normalized identifiers produce an automatic match."""
    exact = []
    for candidate in candidates:
        fields = (
            query.normalized_phone and query.normalized_phone == candidate.normalized_phone,
            query.normalized_email and query.normalized_email == candidate.normalized_email,
            query.social_provider and query.social_provider == candidate.social_provider
            and query.social_subject and query.social_subject == candidate.social_subject,
        )
        if any(fields):
            exact.append(candidate.customer_reference)
    unique = set(exact)
    if len(unique) == 1:
        return IdentityResult.MATCHED
    if len(unique) > 1:
        return IdentityResult.MULTIPLE_MATCHES
    return IdentityResult.NO_MATCH


class CommunicationProvider(Protocol):
    def health_check(self) -> bool: ...
    def send_approved(self, message: OutboundMessage) -> str: ...
    def read_delivery_status(self, provider_reference: str) -> MessageState: ...


class StagingMessageStore:
    """Tenant-scoped idempotent store; performs no external delivery."""

    def __init__(self):
        self._messages: dict[tuple[str, str], OutboundMessage] = {}

    def create(self, message: OutboundMessage) -> OutboundMessage:
        key = (message.tenant_id, message.idempotency_key)
        prior = self._messages.get(key)
        if prior is not None:
            if prior.model_dump() != message.model_dump():
                raise ValueError("idempotency key reused with different payload")
            return prior
        self._messages[key] = message
        return message

    def get(self, tenant_id: str, idempotency_key: str) -> OutboundMessage | None:
        return self._messages.get((tenant_id, idempotency_key))

