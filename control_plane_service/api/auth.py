from __future__ import annotations

import hashlib
import hmac
import ipaddress
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass


OperatorIdentity = tuple[str, str, str | None]
FallbackOperator = Callable[[str], OperatorIdentity | None]


@dataclass(frozen=True)
class OperatorResolution:
    identity: OperatorIdentity | None
    error: str | None = None

    @property
    def authorized(self) -> bool:
        return self.identity is not None and self.error is None


def _trusted_proxy_context(
    peer_value: str,
    cidr_values: str,
) -> tuple[ipaddress._BaseAddress | None, tuple[ipaddress._BaseNetwork, ...]]:
    try:
        networks = tuple(
            ipaddress.ip_network(value.strip())
            for value in cidr_values.split(",")
            if value.strip()
        )
        peer = ipaddress.ip_address(peer_value)
    except ValueError:
        return None, ()
    return peer, networks


def resolve_operator(
    headers: Mapping[str, str],
    peer_value: str,
    roles: Set[str],
    *,
    trusted_proxy_cidrs: str,
    gateway_verifier: str,
    fallback_operator: FallbackOperator,
) -> OperatorResolution:
    """Resolve the existing trusted-gateway or bearer-token operator identity."""
    peer, proxy_cidrs = _trusted_proxy_context(peer_value, trusted_proxy_cidrs)
    client = headers.get("X-Authenticated-Client", "") or ""
    tenant = headers.get("X-Authenticated-Tenant", "") or ""
    gateway_role = headers.get("X-Authenticated-Role", "tenant_admin") or "tenant_admin"
    gateway_secret = headers.get("X-Codestra-Gateway-Secret", "") or ""
    supplied_verifier = hashlib.sha256(gateway_secret.encode()).hexdigest()
    gateway_valid = bool(gateway_verifier) and hmac.compare_digest(
        gateway_verifier,
        supplied_verifier,
    )
    trusted_gateway = (
        peer is not None
        and bool(client)
        and gateway_valid
        and gateway_role in roles
        and any(peer in network for network in proxy_cidrs)
    )
    if trusted_gateway:
        if gateway_role == "tenant_admin" and not tenant:
            return OperatorResolution(None, "forbidden")
        return OperatorResolution((client, gateway_role, tenant or None))

    bearer = (headers.get("Authorization", "") or "").removeprefix("Bearer ")
    identity = fallback_operator(bearer)
    if not identity or identity[1] not in roles:
        return OperatorResolution(None, "forbidden")
    return OperatorResolution(identity)
