"""Keycloak/OIDC service-token contract independent of secret material."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


class IdentityError(ValueError):
    """A service identity is not authorized for the requested tenant."""


@dataclass(frozen=True)
class ServiceIdentityContract:
    issuer: str
    audience: str
    client_id: str
    required_roles: frozenset[str]
    allowed_tenants: frozenset[str]
    maximum_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.issuer.startswith("https://"):
            raise IdentityError("issuer must use HTTPS")
        if not self.audience or not self.client_id or not self.required_roles:
            raise IdentityError("audience, client and roles are required")
        if not self.allowed_tenants or self.maximum_ttl_seconds > 900:
            raise IdentityError("tenant allowlist or token TTL is unsafe")

    def authorize(
        self,
        claims: dict,
        *,
        tenant_id: str,
        signature_verified: bool,
        now: datetime | None = None,
    ) -> None:
        if not signature_verified:
            raise IdentityError("token signature is invalid")
        current = int((now or datetime.now(timezone.utc)).timestamp())
        if claims.get("iss") != self.issuer:
            raise IdentityError("issuer is invalid")
        audience = claims.get("aud", ())
        audience = {audience} if isinstance(audience, str) else set(audience)
        if self.audience not in audience:
            raise IdentityError("audience is invalid")
        if claims.get("azp") != self.client_id:
            raise IdentityError("authorized party is invalid")
        issued = int(claims.get("iat", 0))
        expiry = int(claims.get("exp", 0))
        if issued > current + 30 or expiry <= current:
            raise IdentityError("token is not currently valid")
        if expiry - issued > self.maximum_ttl_seconds:
            raise IdentityError("token TTL exceeds policy")
        roles = set(claims.get("realm_access", {}).get("roles", ()))
        if not self.required_roles <= roles:
            raise IdentityError("required role is missing")
        if tenant_id not in self.allowed_tenants or claims.get("tenant_id") != tenant_id:
            raise IdentityError("tenant binding is invalid")
        if not claims.get("jti"):
            raise IdentityError("token identity is missing")
