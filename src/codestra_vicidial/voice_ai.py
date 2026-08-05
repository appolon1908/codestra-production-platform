"""Staging Voice AI media/session governance with no telephony control."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Speaker(StrEnum):
    AGENT = "AGENT"
    CUSTOMER = "CUSTOMER"
    UNKNOWN = "UNKNOWN"


class Sentiment(StrEnum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    FRUSTRATED = "FRUSTRATED"
    ANGRY = "ANGRY"
    UNCERTAIN = "UNCERTAIN"


class Intent(StrEnum):
    SALES = "SALES"
    SUPPORT = "SUPPORT"
    BILLING = "BILLING"
    CANCELLATION = "CANCELLATION"
    CALLBACK = "CALLBACK"
    APPOINTMENT = "APPOINTMENT"
    COMPLAINT = "COMPLAINT"
    INFORMATION = "INFORMATION"
    WRONG_NUMBER = "WRONG_NUMBER"
    OPT_OUT = "OPT_OUT"


class MediaClaims(StrictModel):
    token_id: UUID
    tenant_id: str
    workspace_id: str
    call_id: str
    session_id: str
    extension: int
    number_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_at: int
    expires_at: int
    max_session_seconds: int = Field(gt=0, le=7200)

    @model_validator(mode="after")
    def expiry_after_issue(self):
        if self.expires_at <= self.issued_at:
            raise ValueError("token expiry must follow issue time")
        return self


@dataclass
class MediaTokenVerifier:
    key: bytes
    allowed_extensions: frozenset[int]
    allowed_number_hashes: frozenset[str]
    used_token_ids: set[str] = field(default_factory=set)

    def sign(self, claims: MediaClaims) -> str:
        body = claims.model_dump_json().encode()
        signature = hmac.new(self.key, body, hashlib.sha256).hexdigest()
        return body.hex() + "." + signature

    def verify(self, token: str, *, tenant_id: str, workspace_id: str,
               call_id: str, now: int | None = None) -> MediaClaims:
        try:
            body_hex, signature = token.split(".", 1)
            body = bytes.fromhex(body_hex)
        except (ValueError, TypeError) as exc:
            raise PermissionError("invalid media token") from exc
        expected = hmac.new(self.key, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("invalid media signature")
        claims = MediaClaims.model_validate_json(body)
        current = int(time.time()) if now is None else now
        if current < claims.issued_at - 30 or current >= claims.expires_at:
            raise PermissionError("expired media token")
        if claims.tenant_id != tenant_id or claims.workspace_id != workspace_id:
            raise PermissionError("cross-tenant media context")
        if claims.call_id != call_id:
            raise PermissionError("invalid call ID")
        if claims.extension not in self.allowed_extensions:
            raise PermissionError("unapproved extension")
        if claims.number_hash not in self.allowed_number_hashes:
            raise PermissionError("unapproved number")
        token_id = str(claims.token_id)
        if token_id in self.used_token_ids:
            raise PermissionError("media token replay")
        self.used_token_ids.add(token_id)
        return claims


class TranscriptSegment(StrictModel):
    segment_id: UUID
    call_id: str
    speaker: Speaker
    started_at: float = Field(ge=0)
    ended_at: float = Field(gt=0)
    language: str
    text: str
    confidence: float = Field(ge=0, le=1)
    final: bool

    @model_validator(mode="after")
    def validate_times(self):
        if self.ended_at <= self.started_at:
            raise ValueError("segment end must follow start")
        return self


class Classification(StrictModel):
    sentiment: Sentiment
    sentiment_confidence: float = Field(ge=0, le=1)
    intent: Intent
    intent_confidence: float = Field(ge=0, le=1)
    advisory: bool = True


class CallSummary(StrictModel):
    call_id: str
    call_purpose: str
    customer_intent: str
    customer_questions: list[str]
    agent_responses: list[str]
    products_discussed: list[str]
    objections: list[str]
    commitments: list[str]
    appointment_request: bool
    callback_request: bool
    complaint: bool
    escalation: bool
    disposition_recommendation: str
    follow_up_actions: list[str]
    risk_warnings: list[str]
    advisory: bool = True


class QAScore(StrictModel):
    call_id: str
    scores: dict[str, int]
    evidence_references: list[str]
    advisory: bool = True

    @field_validator("scores")
    @classmethod
    def validate_scores(cls, values: dict[str, int]) -> dict[str, int]:
        required = {"greeting", "disclosure", "identity_verification", "script_adherence",
                    "listening", "accuracy", "product_knowledge", "professionalism",
                    "empathy", "objection_handling", "compliance", "resolution",
                    "disposition_accuracy", "call_closing"}
        if set(values) != required or any(score < 0 or score > 5 for score in values.values()):
            raise ValueError("QA scorecard must contain all 0-5 criteria")
        return values


@dataclass
class BargeInController:
    speaking: bool = False
    buffered_audio: list[bytes] = field(default_factory=list)

    def start_tts(self, chunks: list[bytes]) -> None:
        self.speaking = True
        self.buffered_audio = list(chunks)

    def voice_activity(self) -> dict[str, Any]:
        stopped = self.speaking
        discarded = sum(len(chunk) for chunk in self.buffered_audio)
        self.speaking = False
        self.buffered_audio.clear()
        return {"tts_stopped": stopped, "discarded_bytes": discarded}


PROHIBITED_AI_ACTIONS = frozenset({
    "accept_payment", "issue_refund", "change_contract", "execute_trade",
    "medical_decision", "legal_decision", "activate_campaign",
    "call_arbitrary_number", "change_carrier", "change_trunk",
})


def authorize_ai_action(action: str) -> None:
    if action in PROHIBITED_AI_ACTIONS:
        raise PermissionError("AI action is prohibited")

