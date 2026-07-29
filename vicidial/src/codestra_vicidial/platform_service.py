from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Protocol

from .platform_models import (
    AsteriskEndpointRequest,
    ContactRevokeRequest,
    InternalCallRequest,
    OperationEnvelope,
    VicidialPhoneRequest,
    VicidialUserRequest,
)
from .platform_security import ExecutionGrantVerifier
from .state import StateStore


class PlatformPolicyDenied(PermissionError):
    pass


class OperationReporter(Protocol):
    def register(self, operation: OperationEnvelope, action: str) -> None: ...
    def transition(
        self, operation: OperationEnvelope, sequence: int, state: str
    ) -> None: ...
    def terminal(self, operation: OperationEnvelope, result: dict[str, Any]) -> None: ...


class DisabledOperationReporter:
    """Fail-closed until the registry-backed middleware endpoint is configured."""

    def register(self, operation: OperationEnvelope, action: str) -> None:
        raise PlatformPolicyDenied("middleware operation reporting is not configured")

    def transition(
        self, operation: OperationEnvelope, sequence: int, state: str
    ) -> None:
        raise PlatformPolicyDenied("middleware operation reporting is not configured")

    def terminal(self, operation: OperationEnvelope, result: dict[str, Any]) -> None:
        raise PlatformPolicyDenied("middleware operation reporting is not configured")


@dataclass(frozen=True)
class PlatformFlags:
    adapter_api_enabled: bool = False
    vicidial_reads_enabled: bool = False
    asterisk_reads_enabled: bool = False
    reconciliation_enabled: bool = False
    metrics_enabled: bool = False
    vicidial_user_writes_enabled: bool = False
    vicidial_phone_writes_enabled: bool = False
    vicidial_campaign_writes_enabled: bool = False
    vicidial_lead_writes_enabled: bool = False
    asterisk_endpoint_writes_enabled: bool = False
    asterisk_contact_revocation_enabled: bool = False
    asterisk_reload_enabled: bool = False
    internal_calls_enabled: bool = False
    call_hangup_enabled: bool = False
    call_dtmf_enabled: bool = False
    call_hold_enabled: bool = False
    call_resume_enabled: bool = False
    transfers_enabled: bool = False
    external_calls_enabled: bool = False
    customer_calls_enabled: bool = False
    local_kill_switch: bool = True
    configuration_version: int = 1

    @classmethod
    def from_environment(cls) -> PlatformFlags:
        values: dict[str, Any] = {}
        for field in fields(cls):
            if isinstance(field.default, bool):
                values[field.name] = os.environ.get(field.name.upper(), "false") == "true"
        values["local_kill_switch"] = (
            os.environ.get("TELEPHONY_ADAPTER_LOCAL_KILL_SWITCH", "true") == "true"
        )
        values["configuration_version"] = int(
            os.environ.get("TELEPHONY_CONFIGURATION_VERSION", "1")
        )
        return cls(**values)

    def snapshot(self, environment: str) -> dict[str, Any]:
        safe = {
            key: value
            for key, value in asdict(self).items()
            if key != "local_kill_switch"
        }
        safe["environment"] = environment
        canonical = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
        safe["configuration_checksum"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
        return safe


class LocalTelephonyBackend:
    """Deterministic adapter-local backend; production drivers implement this API."""

    def __init__(self, configuration_root: Path):
        self.configuration_root = configuration_root
        self.users: dict[str, dict] = {}
        self.phones: dict[str, dict] = {}
        self.endpoints: dict[str, dict] = {}
        self.contacts: dict[str, dict[str, dict]] = {}
        self.calls: dict[str, dict] = {}
        self.campaigns: dict[str, dict] = {}
        self.lists: dict[str, dict] = {}
        self.leads: dict[str, dict] = {}

    def put_user(self, request: VicidialUserRequest) -> dict:
        actual = {
            "agent_public_id": request.agent_public_id,
            "target_public_id": request.target_public_id,
            "user_group": request.user_group,
            "state": request.state,
            "desired_state_version": request.desired_state_version,
        }
        self.users[request.agent_public_id] = actual
        return dict(actual)

    def put_phone(self, request: VicidialPhoneRequest) -> dict:
        actual = {
            "phone_public_id": request.phone_public_id,
            "agent_public_id": request.agent_public_id,
            "target_public_id": request.target_public_id,
            "state": request.state,
            "desired_state_version": request.desired_state_version,
        }
        self.phones[request.phone_public_id] = actual
        return dict(actual)

    @staticmethod
    def _render_endpoint(request: AsteriskEndpointRequest) -> str:
        # The extension is resolved by a deployment driver from the committed
        # reservation. Request text can never select it.
        return "\n".join(
            (
                f"; operation={request.operation_public_id}",
                f"; reservation={request.allocation_reservation_public_id}",
                f"[{request.endpoint_public_id}]",
                "type=endpoint",
                f"context={request.context_key}",
                "allow=!all,ulaw",
                "direct_media=no",
                "trust_id_outbound=no",
                f"; state={request.state}",
                "",
            )
        )

    def put_endpoint(self, request: AsteriskEndpointRequest) -> dict:
        rendered = self._render_endpoint(request)
        checksum = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()
        self.configuration_root.mkdir(parents=True, exist_ok=True)
        target = self.configuration_root / f"{request.endpoint_public_id}.conf"
        rollback = self.configuration_root / f"{request.endpoint_public_id}.previous"
        temporary = self.configuration_root / f".{request.endpoint_public_id}.new"
        if target.exists():
            rollback.write_bytes(target.read_bytes())
        temporary.write_text(rendered)
        if "type=endpoint" not in temporary.read_text():
            temporary.unlink(missing_ok=True)
            raise ValueError("Asterisk endpoint configuration validation failed")
        os.replace(temporary, target)
        actual = {
            "endpoint_public_id": request.endpoint_public_id,
            "agent_public_id": request.agent_public_id,
            "target_public_id": request.target_public_id,
            "state": request.state,
            "context_key": request.context_key,
            "external_route_allowed": False,
            "transfer_allowed": False,
            "desired_state_version": request.desired_state_version,
            "configuration_checksum": checksum,
            "rollback_available": rollback.exists(),
        }
        self.endpoints[request.endpoint_public_id] = actual
        return dict(actual)

    def revoke_contacts(
        self, endpoint_id: str, contact_id: str | None = None
    ) -> dict:
        contacts = self.contacts.setdefault(endpoint_id, {})
        selected = [contact_id] if contact_id else list(contacts)
        for value in selected:
            if value in contacts:
                contacts[value]["state"] = "REVOKED"
        return {
            "endpoint_public_id": endpoint_id,
            "revoked": sorted(value for value in selected if value in contacts),
            "contacts": list(contacts.values()),
        }

    def internal_call(self, request: InternalCallRequest) -> dict:
        actual = {
            "call_public_id": request.call_public_id,
            "source_endpoint_public_id": request.source_endpoint_public_id,
            "destination_endpoint_public_id": request.destination_endpoint_public_id,
            "state": "REQUESTED",
            "maximum_duration_seconds": request.maximum_duration_seconds,
            "external": False,
            "customer": False,
        }
        self.calls[request.call_public_id] = actual
        return dict(actual)


class PlatformAdapterService:
    def __init__(
        self,
        state: StateStore,
        flags: PlatformFlags,
        grants: ExecutionGrantVerifier,
        backend: LocalTelephonyBackend,
        *,
        environment: str = "staging",
        resource_allowlist: frozenset[str] = frozenset(),
        reporter: OperationReporter | None = None,
    ):
        self.state = state
        self.flags = flags
        self.grants = grants
        self.backend = backend
        self.environment = environment
        self.resource_allowlist = resource_allowlist
        self.reporter = reporter or DisabledOperationReporter()

    def effective_flags(self) -> dict[str, Any]:
        return self.flags.snapshot(self.environment)

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "service_key": "telephony-adapter",
            "environment": self.environment,
            "families": [
                "vicidial.users", "vicidial.phones", "vicidial.readback",
                "asterisk.endpoints", "asterisk.contacts",
                "asterisk.dialplan.read", "asterisk.runtime.read",
                "asterisk.internal_calls", "telephony.reconciliation",
            ],
            "arbitrary_sql": False,
            "arbitrary_shell": False,
            "arbitrary_file_write": False,
            "raw_dialplan_edit": False,
        }

    def evaluate(self, action: str, target: str, local_flag: bool) -> dict[str, Any]:
        allowed = (
            self.flags.adapter_api_enabled
            and not self.flags.local_kill_switch
            and local_flag
            and target in self.resource_allowlist
        )
        return {
            "action": action,
            "target_hash": "sha256:" + hashlib.sha256(target.encode()).hexdigest(),
            "allowed": allowed,
            "requires_execution_grant": True,
            "requires_action_budget": True,
        }

    def _mutate(
        self, action: str, request: OperationEnvelope, local_flag: bool, apply
    ) -> dict[str, Any]:
        policy = self.evaluate(action, request.target_public_id, local_flag)
        if not policy["allowed"]:
            raise PlatformPolicyDenied("adapter action is disabled or not allowlisted")
        claims, grant_digest, now = self.grants.verify(
            request.execution_grant, request, action
        )
        digest = self.state.digest(request.model_dump(mode="json"))
        prior = self.state.prior(action, request.idempotency_key, digest)
        if prior is not None:
            return prior | {"idempotent_replay": True}
        remaining = self.grants.consume(claims, grant_digest, now)
        self.reporter.register(request, action)
        self.reporter.transition(request, 1, "AUTHORIZED")
        actual = apply()
        actual_hash = "sha256:" + self.state.digest(actual)
        result = {
            "operation_public_id": request.operation_public_id,
            "command_public_id": request.command_public_id,
            "target_public_id": request.target_public_id,
            "requested_state_version": request.desired_state_version,
            "applied_state_version": actual["desired_state_version"],
            "observed_state_version": actual["desired_state_version"],
            "application_hash": request.desired_state_hash,
            "readback_hash": actual_hash,
            "configuration_checksum": actual.get(
                "configuration_checksum",
                self.effective_flags()["configuration_checksum"],
            ),
            "policy_hash": request.policy_hash,
            "correlation_id": request.correlation_id,
            "action_budget_remaining": remaining,
            "auto_disabled": remaining == 0,
            "actual": actual,
        }
        result["result_hash"] = "sha256:" + self.state.digest(result)
        self.reporter.transition(request, 2, "READBACK_VERIFIED")
        self.reporter.terminal(request, result)
        self.state.record(action, request.idempotency_key, digest, result)
        self.state.audit(
            request.correlation_id, claims.grant_id, action,
            request.target_public_id, "success", result,
        )
        return result | {"idempotent_replay": False}

    def put_user(self, request: VicidialUserRequest) -> dict:
        return self.user_action(request, "apply")

    def user_action(self, request: VicidialUserRequest, verb: str) -> dict:
        return self._mutate(
            f"telephony.vicidial.user.{verb}", request,
            self.flags.vicidial_user_writes_enabled,
            lambda: self.backend.put_user(request),
        )

    def put_phone(self, request: VicidialPhoneRequest) -> dict:
        return self.phone_action(request, "apply")

    def phone_action(self, request: VicidialPhoneRequest, verb: str) -> dict:
        return self._mutate(
            f"telephony.vicidial.phone.{verb}", request,
            self.flags.vicidial_phone_writes_enabled,
            lambda: self.backend.put_phone(request),
        )

    def put_endpoint(self, request: AsteriskEndpointRequest) -> dict:
        return self.endpoint_action(request, "apply")

    def endpoint_action(self, request: AsteriskEndpointRequest, verb: str) -> dict:
        return self._mutate(
            f"telephony.asterisk.endpoint.{verb}", request,
            self.flags.asterisk_endpoint_writes_enabled,
            lambda: self.backend.put_endpoint(request),
        )

    def revoke_contact(self, request: ContactRevokeRequest) -> dict:
        return self._mutate(
            "telephony.asterisk.contact.revoke", request,
            self.flags.asterisk_contact_revocation_enabled,
            lambda: {
                **self.backend.revoke_contacts(
                    request.target_public_id, request.contact_public_id
                ),
                "desired_state_version": request.desired_state_version,
            },
        )

    def internal_call(self, request: InternalCallRequest) -> dict:
        if (
            self.flags.external_calls_enabled
            or self.flags.customer_calls_enabled
            or self.flags.transfers_enabled
        ):
            raise PlatformPolicyDenied("external/customer/transfer flags must remain false")
        for endpoint_id in (
            request.source_endpoint_public_id,
            request.destination_endpoint_public_id,
        ):
            endpoint = self.backend.endpoints.get(endpoint_id)
            if endpoint is None or endpoint.get("external_route_allowed"):
                raise PlatformPolicyDenied("internal call endpoint is not approved")
        return self._mutate(
            "telephony.asterisk.internal_call.create", request,
            self.flags.internal_calls_enabled,
            lambda: {
                **self.backend.internal_call(request),
                "desired_state_version": request.desired_state_version,
            },
        )
