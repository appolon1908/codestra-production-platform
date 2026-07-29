from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import jwt

from .platform_models import ExecutionGrantClaims, OperationEnvelope
from .state import StateStore


class TokenDenied(PermissionError):
    pass


@dataclass(frozen=True)
class ServiceIdentity:
    subject: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class KeycloakTokenVerifier:
    issuer: str
    audience: str
    verification_key: str
    algorithms: tuple[str, ...] = ("RS256",)
    approved_subjects: frozenset[str] = frozenset(
        {"codestra-middleware", "codestra-provisioning"}
    )

    def verify(self, token: str, required_scope: str) -> ServiceIdentity:
        try:
            claims = jwt.decode(
                token,
                self.verification_key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenDenied("invalid service access token") from exc
        subject = str(claims["sub"])
        scopes = frozenset(str(claims.get("scope", "")).split())
        if subject not in self.approved_subjects:
            raise TokenDenied("service identity is not approved")
        if required_scope not in scopes:
            raise TokenDenied("service access token is missing scope")
        return ServiceIdentity(subject, scopes)


@dataclass(frozen=True)
class ExecutionGrantVerifier:
    key: bytes
    state: StateStore
    max_clock_skew_seconds: int = 30

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def issue(self, claims: ExecutionGrantClaims) -> str:
        payload = claims.model_dump_json().encode()
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        signature = hmac.new(self.key, encoded.encode(), hashlib.sha256).digest()
        return encoded + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    def verify(
        self, token: str, envelope: OperationEnvelope, action: str, *,
        now: int | None = None,
    ) -> tuple[ExecutionGrantClaims, str, int]:
        try:
            encoded, supplied = token.split(".", 1)
            expected = hmac.new(self.key, encoded.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, self._decode(supplied)):
                raise TokenDenied("invalid execution grant signature")
            claims = ExecutionGrantClaims.model_validate_json(self._decode(encoded))
        except (ValueError, json.JSONDecodeError) as exc:
            raise TokenDenied("invalid execution grant") from exc
        current = int(time.time()) if now is None else now
        if claims.issued_at > current + self.max_clock_skew_seconds:
            raise TokenDenied("execution grant issued in the future")
        bindings: dict[str, Any] = {
            "command_id": envelope.command_public_id,
            "operation_id": envelope.operation_public_id,
            "environment": envelope.environment,
            "business_unit_public_id": envelope.business_unit_public_id,
            "campaign_public_id": envelope.campaign_public_id,
            "target_public_id": envelope.target_public_id,
            "action": action,
            "desired_state_version": envelope.desired_state_version,
            "allocation_reservation_public_id":
                envelope.allocation_reservation_public_id,
            "idempotency_key": envelope.idempotency_key,
            "policy_hash": envelope.policy_hash,
            "feature_flag_snapshot_hash": envelope.feature_flag_snapshot_hash,
            "middleware_action_enabled": envelope.middleware_action_enabled,
        }
        for field, expected_value in bindings.items():
            if getattr(claims, field) != expected_value:
                raise TokenDenied(f"execution grant {field} mismatch")
        if claims.expires_at < current:
            raise TokenDenied("execution grant expired")
        return claims, hashlib.sha256(token.encode()).hexdigest(), current

    def consume(
        self, claims: ExecutionGrantClaims, digest: str, now: int
    ) -> int:
        return self.state.consume_grant(
            claims.grant_id,
            digest,
            claims.maximum_actions,
            claims.expires_at,
            now,
        )
