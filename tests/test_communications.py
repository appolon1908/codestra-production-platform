import pytest
from pydantic import ValidationError

from codestra_vicidial.communications import (
    Channel, ConsentState, Conversation, IdentityCandidate, IdentityResult,
    MessageState, OutboundMessage, StagingMessageStore, resolve_identity,
)
from codestra_vicidial.providers import MockProvider, ProviderUnavailable


def message(**overrides):
    conversation = Conversation(
        tenant_id="tenant-a", workspace_id="workspace-a", channel=Channel.SMS,
        channel_account="sender-a",
    )
    values = dict(
        conversation_id=conversation.conversation_id, tenant_id="tenant-a",
        workspace_id="workspace-a", channel=Channel.SMS,
        sender_account="sender-a", recipient_reference="customer:1",
        purpose="support", body="Approved staging fixture",
        state=MessageState.WAITING_FOR_APPROVAL,
        idempotency_key="message-fixture-1", consent_state=ConsentState.GRANTED,
    )
    values.update(overrides)
    return OutboundMessage(**values)


def test_denied_consent_blocks_outbound():
    with pytest.raises(ValidationError):
        message(consent_state=ConsentState.DENIED)
    assert message(consent_state=ConsentState.DENIED, state=MessageState.BLOCKED).state == "BLOCKED"


def test_delivery_state_requires_approval():
    with pytest.raises(ValidationError):
        message(state=MessageState.QUEUED)
    assert message(state=MessageState.QUEUED, approval_reference="approval:1").state == "QUEUED"


def test_idempotency_is_tenant_scoped_and_payload_bound():
    store = StagingMessageStore()
    original = message()
    assert store.create(original) == store.create(original)
    with pytest.raises(ValueError):
        store.create(original.model_copy(update={"body": "changed"}))
    other = original.model_copy(update={"tenant_id": "tenant-b"})
    assert store.create(other).tenant_id == "tenant-b"


def test_identity_resolution_prevents_ambiguous_merge():
    query = IdentityCandidate(customer_reference="incoming", normalized_phone="+15551234567")
    assert resolve_identity(query, []) is IdentityResult.NO_MATCH
    one = [IdentityCandidate(customer_reference="c1", normalized_phone="+15551234567")]
    assert resolve_identity(query, one) is IdentityResult.MATCHED
    two = one + [IdentityCandidate(customer_reference="c2", normalized_phone="+15551234567")]
    assert resolve_identity(query, two) is IdentityResult.MULTIPLE_MATCHES


def test_cross_tenant_lookup_is_denied_by_keyspace():
    store = StagingMessageStore()
    store.create(message())
    assert store.get("tenant-b", "message-fixture-1") is None


def test_human_and_ai_dual_assignment_is_rejected():
    with pytest.raises(ValidationError):
        Conversation(
            tenant_id="tenant-a", workspace_id="workspace-a", channel=Channel.WEB_CHAT,
            channel_account="web", assigned_agent="agent-1", assigned_ai_employee="ai-1",
        )


def test_provider_rejects_unapproved_message():
    provider = MockProvider("sms")
    with pytest.raises(PermissionError):
        provider.send_approved(message())


def test_provider_outage_fails_closed():
    provider = MockProvider("whatsapp", healthy=False)
    approved = message(state=MessageState.APPROVED, approval_reference="approval:1")
    with pytest.raises(ProviderUnavailable):
        provider.send_approved(approved)


def test_provider_duplicate_send_is_idempotent():
    provider = MockProvider("email")
    approved = message(state=MessageState.APPROVED, approval_reference="approval:1")
    first = provider.send_approved(approved)
    assert provider.send_approved(approved) == first
    assert len(provider.sent) == 1
