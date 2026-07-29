from __future__ import annotations

import hashlib
from typing import Annotated, Protocol

from fastapi import APIRouter, Header, HTTPException

from .platform_models import (
    AsteriskEndpointRequest,
    CallControlRequest,
    ContactRevokeRequest,
    InternalCallRequest,
    VicidialPhoneRequest,
    VicidialUserRequest,
)
from .platform_security import ServiceIdentity, TokenDenied
from .platform_service import PlatformAdapterService, PlatformPolicyDenied


class TokenVerifier(Protocol):
    def verify(self, token: str, required_scope: str) -> ServiceIdentity: ...


Authorization = Annotated[str, Header(alias="Authorization")]


def platform_router(
    service: PlatformAdapterService, token_verifier: TokenVerifier
) -> APIRouter:
    router = APIRouter()

    def authorize(header: str, scope: str) -> ServiceIdentity:
        if not header.startswith("Bearer "):
            raise HTTPException(401, "bearer service token required")
        try:
            return token_verifier.verify(header.removeprefix("Bearer "), scope)
        except TokenDenied as exc:
            raise HTTPException(403, str(exc)) from exc

    def mutation(header: str, scope: str, handler, request):
        authorize(header, scope)
        try:
            return handler(request)
        except PlatformPolicyDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def read(header: str, enabled: bool):
        authorize(header, "telephony.read")
        if not service.flags.adapter_api_enabled or not enabled:
            raise HTTPException(503, "adapter read capability is disabled")

    @router.get("/health/live")
    def live():
        return {"status": "live", "service_key": "telephony-adapter"}

    @router.get("/health/ready")
    def ready(authorization: Authorization):
        authorize(authorization, "monitor.read")
        return {
            "status": "ready" if service.flags.adapter_api_enabled else "not_ready",
            "configuration_checksum":
                service.effective_flags()["configuration_checksum"],
        }

    @router.get("/.well-known/codestra-service")
    def identity(authorization: Authorization):
        authorize(authorization, "service.attest")
        return {
            "service_key": "telephony-adapter",
            "environment": service.environment,
            "configuration_checksum":
                service.effective_flags()["configuration_checksum"],
        }

    @router.get("/metrics")
    def metrics(authorization: Authorization):
        authorize(authorization, "metrics.read")
        if not service.flags.metrics_enabled:
            raise HTTPException(503, "metrics disabled")
        return {
            "telephony_adapter_up": 1,
            "telephony_adapter_kill_switch":
                int(service.flags.local_kill_switch),
        }

    @router.get("/api/v1/telephony/capabilities")
    def capabilities(authorization: Authorization):
        authorize(authorization, "telephony.read")
        return service.capabilities()

    @router.get("/api/v1/telephony/effective-flags")
    def effective_flags(authorization: Authorization):
        authorize(authorization, "telephony.read")
        return service.effective_flags()

    @router.post("/api/v1/telephony/policy/evaluations")
    def evaluate(
        action: str, target_public_id: str, authorization: Authorization
    ):
        authorize(authorization, "telephony.policy.evaluate")
        return service.evaluate(action, target_public_id, False)

    @router.put("/api/v1/vicidial/users/{agent_public_id}")
    def put_user(
        agent_public_id: str, body: VicidialUserRequest,
        authorization: Authorization,
    ):
        if agent_public_id != body.agent_public_id:
            raise HTTPException(409, "agent route binding mismatch")
        return mutation(
            authorization, "telephony.vicidial.users.apply", service.put_user, body
        )

    @router.get("/api/v1/vicidial/users/{agent_public_id}")
    def get_user(agent_public_id: str, authorization: Authorization):
        read(authorization, service.flags.vicidial_reads_enabled)
        value = service.backend.users.get(agent_public_id)
        if value is None:
            raise HTTPException(404, "VICIdial user not found")
        return value

    def user_state_handler(verb: str, expected_state: str):
        def handler(
            agent_public_id: str, body: VicidialUserRequest,
            authorization: Authorization,
        ):
            if agent_public_id != body.agent_public_id or body.state != expected_state:
                raise HTTPException(409, "user state route binding mismatch")
            return mutation(
                authorization,
                f"telephony.vicidial.users.{verb}",
                lambda request: service.user_action(request, verb),
                body,
            )
        return handler

    for verb, state in (("enable", "ENABLED"), ("disable", "DISABLED")):
        router.add_api_route(
            f"/api/v1/vicidial/users/{{agent_public_id}}/{verb}",
            user_state_handler(verb, state),
            methods=["POST"],
        )

    @router.post("/api/v1/vicidial/users/{agent_public_id}/reconcile")
    def reconcile_user(
        agent_public_id: str, body: VicidialUserRequest,
        authorization: Authorization,
    ):
        authorize(authorization, "telephony.reconciliation.create")
        actual = service.backend.users.get(agent_public_id)
        matches = bool(actual) and all((
            actual.get("agent_public_id") == body.agent_public_id,
            actual.get("user_group") == body.user_group,
            actual.get("state") == body.state,
            actual.get("desired_state_version") == body.desired_state_version,
        ))
        return {
            "target_public_id": agent_public_id,
            "status": "complete" if matches else "drift_detected",
            "actual": actual,
        }

    @router.put("/api/v1/vicidial/phones/{phone_public_id}")
    def put_phone(
        phone_public_id: str, body: VicidialPhoneRequest,
        authorization: Authorization,
    ):
        if phone_public_id != body.phone_public_id:
            raise HTTPException(409, "phone route binding mismatch")
        return mutation(
            authorization, "telephony.vicidial.phones.apply",
            service.put_phone, body,
        )

    @router.get("/api/v1/vicidial/phones/{phone_public_id}")
    def get_phone(phone_public_id: str, authorization: Authorization):
        read(authorization, service.flags.vicidial_reads_enabled)
        value = service.backend.phones.get(phone_public_id)
        if value is None:
            raise HTTPException(404, "VICIdial phone not found")
        return value

    def phone_state_handler(verb: str, expected_state: str):
        def handler(
            phone_public_id: str, body: VicidialPhoneRequest,
            authorization: Authorization,
        ):
            if phone_public_id != body.phone_public_id or body.state != expected_state:
                raise HTTPException(409, "phone state route binding mismatch")
            return mutation(
                authorization,
                f"telephony.vicidial.phones.{verb}",
                lambda request: service.phone_action(request, verb),
                body,
            )
        return handler

    for verb, state in (("enable", "ENABLED"), ("disable", "DISABLED")):
        router.add_api_route(
            f"/api/v1/vicidial/phones/{{phone_public_id}}/{verb}",
            phone_state_handler(verb, state),
            methods=["POST"],
        )

    @router.post("/api/v1/vicidial/phones/{phone_public_id}/reconcile")
    def reconcile_phone(
        phone_public_id: str, body: VicidialPhoneRequest,
        authorization: Authorization,
    ):
        authorize(authorization, "telephony.reconciliation.create")
        actual = service.backend.phones.get(phone_public_id)
        matches = bool(actual) and all((
            actual.get("phone_public_id") == body.phone_public_id,
            actual.get("agent_public_id") == body.agent_public_id,
            actual.get("state") == body.state,
            actual.get("desired_state_version") == body.desired_state_version,
        ))
        return {
            "target_public_id": phone_public_id,
            "status": "complete" if matches else "drift_detected",
            "actual": actual,
        }

    def resource_reader(store):
        async def get_resource(
            public_id: str, authorization: Authorization,
        ):
            read(authorization, service.flags.vicidial_reads_enabled)
            if public_id not in store:
                raise HTTPException(404, "VICIdial resource not found")
            return store[public_id]
        return get_resource

    for resource, store in (
        ("campaigns", service.backend.campaigns),
        ("lists", service.backend.lists),
        ("leads", service.backend.leads),
    ):
        router.add_api_route(
            f"/api/v1/vicidial/{resource}/{{public_id}}",
            resource_reader(store), methods=["GET"],
        )

    @router.get("/api/v1/vicidial/agents/{agent_public_id}/state")
    def agent_state(agent_public_id: str, authorization: Authorization):
        read(authorization, service.flags.vicidial_reads_enabled)
        return service.backend.users.get(
            agent_public_id, {"agent_public_id": agent_public_id, "state": "UNKNOWN"}
        )

    @router.get("/api/v1/vicidial/runtime")
    def vicidial_runtime(authorization: Authorization):
        read(authorization, service.flags.vicidial_reads_enabled)
        return {
            "users": len(service.backend.users),
            "phones": len(service.backend.phones),
            "campaigns": len(service.backend.campaigns),
        }

    @router.put("/api/v1/asterisk/endpoints/{endpoint_public_id}")
    def put_endpoint(
        endpoint_public_id: str, body: AsteriskEndpointRequest,
        authorization: Authorization,
    ):
        if endpoint_public_id != body.endpoint_public_id:
            raise HTTPException(409, "endpoint route binding mismatch")
        return mutation(
            authorization, "telephony.asterisk.endpoints.apply",
            service.put_endpoint, body,
        )

    @router.get("/api/v1/asterisk/endpoints/{endpoint_public_id}")
    def get_endpoint(endpoint_public_id: str, authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        value = service.backend.endpoints.get(endpoint_public_id)
        if value is None:
            raise HTTPException(404, "Asterisk endpoint not found")
        return value

    def endpoint_state_handler(verb: str, expected_state: str):
        def handler(
            endpoint_public_id: str, body: AsteriskEndpointRequest,
            authorization: Authorization,
        ):
            if (
                endpoint_public_id != body.endpoint_public_id
                or body.state != expected_state
            ):
                raise HTTPException(409, "endpoint state route binding mismatch")
            return mutation(
                authorization,
                f"telephony.asterisk.endpoints.{verb}",
                lambda request: service.endpoint_action(request, verb),
                body,
            )
        return handler

    for verb, state in (("enable", "ENABLED"), ("disable", "DISABLED")):
        router.add_api_route(
            f"/api/v1/asterisk/endpoints/{{endpoint_public_id}}/{verb}",
            endpoint_state_handler(verb, state),
            methods=["POST"],
        )

    @router.post("/api/v1/asterisk/endpoints/{endpoint_public_id}/reconcile")
    def reconcile_endpoint(
        endpoint_public_id: str, body: AsteriskEndpointRequest,
        authorization: Authorization,
    ):
        authorize(authorization, "telephony.reconciliation.create")
        actual = service.backend.endpoints.get(endpoint_public_id)
        matches = bool(actual) and all((
            actual.get("endpoint_public_id") == body.endpoint_public_id,
            actual.get("agent_public_id") == body.agent_public_id,
            actual.get("state") == body.state,
            actual.get("context_key") == body.context_key,
            actual.get("desired_state_version") == body.desired_state_version,
        ))
        return {
            "target_public_id": endpoint_public_id,
            "status": "complete" if matches else "drift_detected",
            "actual": actual,
        }

    @router.get("/api/v1/asterisk/endpoints/{endpoint_public_id}/contacts")
    def contacts(endpoint_public_id: str, authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        return list(service.backend.contacts.get(endpoint_public_id, {}).values())

    @router.get(
        "/api/v1/asterisk/endpoints/{endpoint_public_id}/contacts/{contact_public_id}"
    )
    def contact(
        endpoint_public_id: str, contact_public_id: str,
        authorization: Authorization,
    ):
        read(authorization, service.flags.asterisk_reads_enabled)
        value = service.backend.contacts.get(endpoint_public_id, {}).get(
            contact_public_id
        )
        if value is None:
            raise HTTPException(404, "Asterisk contact not found")
        return value

    @router.post(
        "/api/v1/asterisk/endpoints/{endpoint_public_id}/contacts/"
        "{contact_public_id}/revoke"
    )
    def revoke_contact(
        endpoint_public_id: str, contact_public_id: str,
        body: ContactRevokeRequest, authorization: Authorization,
    ):
        if (
            endpoint_public_id != body.target_public_id
            or contact_public_id != body.contact_public_id
        ):
            raise HTTPException(409, "contact route binding mismatch")
        return mutation(
            authorization, "telephony.asterisk.contacts.revoke",
            service.revoke_contact, body,
        )

    @router.post(
        "/api/v1/asterisk/endpoints/{endpoint_public_id}/contacts/revoke-all"
    )
    def revoke_all(
        endpoint_public_id: str, body: ContactRevokeRequest,
        authorization: Authorization,
    ):
        if endpoint_public_id != body.target_public_id or body.contact_public_id:
            raise HTTPException(409, "contact route binding mismatch")
        return mutation(
            authorization, "asterisk.contacts.revoke_all",
            service.revoke_contact, body,
        )

    @router.get("/api/v1/asterisk/dialplan/contexts")
    def dialplan_contexts(authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        return [{"context_key": "campaign-agent-restricted", "writable": False}]

    @router.get("/api/v1/asterisk/dialplan/contexts/{context_key}")
    def dialplan_context(context_key: str, authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        if context_key != "campaign-agent-restricted":
            raise HTTPException(404, "dialplan context not found")
        return {"context_key": context_key, "external_routes": False}

    @router.get("/api/v1/asterisk/dialplan/routes/{route_key}")
    def dialplan_route(route_key: str, authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        return {
            "route_key_hash": "sha256:" + hashlib.sha256(route_key.encode()).hexdigest(),
            "external": False,
        }

    @router.post("/api/v1/asterisk/dialplan/validations")
    def validate_dialplan(context_key: str, authorization: Authorization):
        authorize(authorization, "telephony.asterisk.dialplan.read")
        return {
            "valid": context_key == "campaign-agent-restricted",
            "raw_dialplan_accepted": False,
        }

    @router.get("/api/v1/asterisk/runtime")
    @router.get("/api/v1/asterisk/runtime/active")
    def runtime(authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        return {
            "active_calls": sum(
                call["state"] not in {"ENDED", "FAILED"}
                for call in service.backend.calls.values()
            ),
            "external_calls": 0,
        }

    @router.get("/api/v1/asterisk/runtime/calls")
    def runtime_calls(authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        return list(service.backend.calls.values())

    @router.get("/api/v1/asterisk/runtime/channels")
    def runtime_channels(authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        return []

    @router.get("/api/v1/asterisk/runtime/bridges")
    def runtime_bridges(authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        return []

    @router.post("/api/v1/asterisk/internal-calls")
    def internal_call(
        body: InternalCallRequest, authorization: Authorization
    ):
        return mutation(
            authorization, "telephony.asterisk.internal_calls.create",
            service.internal_call, body,
        )

    @router.get("/api/v1/asterisk/calls/{call_public_id}")
    def get_call(call_public_id: str, authorization: Authorization):
        read(authorization, service.flags.asterisk_reads_enabled)
        value = service.backend.calls.get(call_public_id)
        if value is None:
            raise HTTPException(404, "call not found")
        return value

    control_flags = {
        "hangup": service.flags.call_hangup_enabled,
        "dtmf": service.flags.call_dtmf_enabled,
        "hold": service.flags.call_hold_enabled,
        "resume": service.flags.call_resume_enabled,
    }
    def control_handler(control: str, enabled: bool):
        async def control_call(
            call_public_id: str, body: CallControlRequest,
            authorization: Authorization,
        ):
            if call_public_id != body.call_public_id:
                raise HTTPException(409, "call route binding mismatch")
            return mutation(
                authorization, f"telephony.asterisk.calls.{control}",
                lambda request: service._mutate(
                    f"telephony.asterisk.call.{control}", request, enabled,
                    lambda: {
                        "call_public_id": request.call_public_id,
                        "state": control.upper(),
                        "desired_state_version": request.desired_state_version,
                    },
                ),
                body,
            )
        return control_call

    for control, enabled in control_flags.items():
        router.add_api_route(
            f"/api/v1/asterisk/calls/{{call_public_id}}/{control}",
            control_handler(control, enabled), methods=["POST"],
        )

    @router.post("/api/v1/telephony/reconciliation/runs")
    def reconciliation(authorization: Authorization):
        authorize(authorization, "telephony.reconciliation.create")
        if not service.flags.reconciliation_enabled:
            raise HTTPException(503, "reconciliation disabled")
        return {
            "run_public_id": "REC-READONLY",
            "status": "complete",
            "unresolved_drift_count": 0,
            "configuration_checksum":
                service.effective_flags()["configuration_checksum"],
        }

    @router.get("/api/v1/telephony/reconciliation/runs/{run_public_id}")
    def reconciliation_read(
        run_public_id: str, authorization: Authorization
    ):
        authorize(authorization, "telephony.reconciliation.read")
        if not service.flags.reconciliation_enabled:
            raise HTTPException(503, "reconciliation disabled")
        return {
            "run_public_id": run_public_id,
            "status": "complete",
            "unresolved_drift_count": 0,
            "configuration_checksum":
                service.effective_flags()["configuration_checksum"],
        }

    return router
