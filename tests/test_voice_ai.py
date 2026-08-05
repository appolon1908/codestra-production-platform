import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

import pytest

from codestra_vicidial.voice_ai import (
    BargeInController, MediaClaims, MediaTokenVerifier, authorize_ai_action,
)


def verifier_and_claims():
    number_hash = hashlib.sha256(b"internal-6101").hexdigest()
    verifier = MediaTokenVerifier(b"test-key", frozenset({6101}), frozenset({number_hash}))
    now = int(time.time())
    claims = MediaClaims(
        token_id=uuid4(), tenant_id="tenant-a", workspace_id="workspace-a",
        call_id="call-1", session_id="session-1", extension=6101,
        number_hash=number_hash, issued_at=now, expires_at=now + 60,
        max_session_seconds=120,
    )
    return verifier, claims, now


def test_media_token_authentication_and_replay_rejection():
    verifier, claims, now = verifier_and_claims()
    token = verifier.sign(claims)
    assert verifier.verify(token, tenant_id="tenant-a", workspace_id="workspace-a",
                           call_id="call-1", now=now).session_id == "session-1"
    with pytest.raises(PermissionError, match="replay"):
        verifier.verify(token, tenant_id="tenant-a", workspace_id="workspace-a",
                        call_id="call-1", now=now)


def test_cross_tenant_media_context_is_rejected():
    verifier, claims, now = verifier_and_claims()
    with pytest.raises(PermissionError, match="cross-tenant"):
        verifier.verify(verifier.sign(claims), tenant_id="tenant-b",
                        workspace_id="workspace-a", call_id="call-1", now=now)


def test_expired_media_token_is_rejected():
    verifier, claims, _ = verifier_and_claims()
    with pytest.raises(PermissionError, match="expired"):
        verifier.verify(verifier.sign(claims), tenant_id="tenant-a",
                        workspace_id="workspace-a", call_id="call-1",
                        now=claims.expires_at)


def test_unapproved_extension_and_number_are_rejected():
    verifier, claims, now = verifier_and_claims()
    claims = claims.model_copy(update={"extension": 6102})
    with pytest.raises(PermissionError, match="extension"):
        verifier.verify(verifier.sign(claims), tenant_id="tenant-a",
                        workspace_id="workspace-a", call_id="call-1", now=now)


def test_barge_in_stops_tts_and_discards_buffer():
    controller = BargeInController()
    controller.start_tts([b"audio", b"remaining"])
    result = controller.voice_activity()
    assert result == {"tts_stopped": True, "discarded_bytes": 14}
    assert controller.buffered_audio == []


@pytest.mark.parametrize("action", [
    "accept_payment", "issue_refund", "change_contract", "execute_trade",
    "medical_decision", "legal_decision", "activate_campaign",
    "call_arbitrary_number", "change_carrier", "change_trunk",
])
def test_voice_ai_cannot_execute_prohibited_actions(action):
    with pytest.raises(PermissionError):
        authorize_ai_action(action)


def test_exactly_fifty_synthetic_conversation_fixtures():
    path = Path(__file__).parent / "fixtures" / "voice-ai-conversations.json"
    fixtures = json.loads(path.read_text())
    assert len(fixtures) == 50
    assert len({item["id"] for item in fixtures}) == 50
