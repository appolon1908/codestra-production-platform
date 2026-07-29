from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PublicId = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{1,15}-[A-Za-z0-9._:-]{3,128}$")]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExecutionGrantClaims(StrictModel):
    grant_id: PublicId
    command_id: PublicId
    operation_id: PublicId
    environment: Literal["staging", "production"]
    business_unit_public_id: PublicId
    campaign_public_id: PublicId
    target_public_id: PublicId
    action: Annotated[str, Field(min_length=5, max_length=96)]
    desired_state_version: Annotated[int, Field(ge=1)]
    allocation_reservation_public_id: PublicId
    idempotency_key: Annotated[str, Field(min_length=8, max_length=255)]
    policy_hash: Sha256
    feature_flag_snapshot_hash: Sha256
    middleware_action_enabled: Literal[True]
    issued_at: int
    expires_at: int
    maximum_actions: Annotated[int, Field(ge=1, le=10)]

    @model_validator(mode="after")
    def short_lived(self):
        if self.expires_at <= self.issued_at or self.expires_at - self.issued_at > 300:
            raise ValueError("execution grant lifetime must not exceed 300 seconds")
        return self


class OperationEnvelope(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    operation_public_id: PublicId
    command_public_id: PublicId
    target_public_id: PublicId
    environment: Literal["staging", "production"]
    business_unit_public_id: PublicId
    campaign_public_id: PublicId
    allocation_reservation_public_id: PublicId
    allocation_reservation_generation: Annotated[int, Field(ge=1)]
    desired_state_version: Annotated[int, Field(ge=1)]
    desired_state_hash: Sha256
    policy_hash: Sha256
    feature_flag_snapshot_hash: Sha256
    middleware_action_enabled: Literal[True]
    correlation_id: PublicId
    idempotency_key: Annotated[str, Field(min_length=8, max_length=255)]
    execution_grant: Annotated[str, Field(min_length=32, max_length=8192)]


class VicidialUserRequest(OperationEnvelope):
    agent_public_id: PublicId
    user_group: Annotated[str, Field(pattern=r"^[A-Z0-9_]{2,20}$")]
    state: Literal["DISABLED", "ENABLED"] = "DISABLED"


class VicidialPhoneRequest(OperationEnvelope):
    phone_public_id: PublicId
    agent_public_id: PublicId
    state: Literal["DISABLED", "ENABLED"] = "DISABLED"


class AsteriskEndpointRequest(OperationEnvelope):
    endpoint_public_id: PublicId
    agent_public_id: PublicId
    state: Literal["DISABLED", "ENABLED"] = "DISABLED"
    context_key: Literal["campaign-agent-restricted"] = "campaign-agent-restricted"
    external_route_allowed: Literal[False] = False
    transfer_allowed: Literal[False] = False


class ContactRevokeRequest(OperationEnvelope):
    contact_public_id: PublicId | None = None
    reason: Annotated[str, Field(min_length=8, max_length=255)]
    active_protected_call_count: Literal[0] = 0


class InternalCallRequest(OperationEnvelope):
    call_public_id: PublicId
    source_endpoint_public_id: PublicId
    destination_endpoint_public_id: PublicId
    maximum_duration_seconds: Annotated[int, Field(ge=1, le=120)]
    purpose: Literal["controlled_internal_staging_acceptance"]


class CallControlRequest(OperationEnvelope):
    call_public_id: PublicId
    reason: Annotated[str, Field(min_length=8, max_length=255)]
