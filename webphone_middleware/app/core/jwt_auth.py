"""Fail-closed Keycloak JWT validation with bounded JWKS caching."""

from dataclasses import dataclass
from typing import Any

import jwt


class JWTAuthError(ValueError):
    pass


@dataclass
class KeycloakValidator:
    issuer: str
    audience: str
    jwks_url: str
    authorized_parties: frozenset[str]
    required_roles: frozenset[str] = frozenset()
    required_scopes: frozenset[str] = frozenset()
    required_environment: str | None = None
    required_business_unit: str | None = None
    required_campaign: str | None = None

    def validate(self, token: str) -> dict[str, Any]:
        if not all(
            (self.issuer, self.audience, self.jwks_url, self.authorized_parties)
        ):
            raise JWTAuthError("Keycloak validation is not configured")
        try:
            key = jwt.PyJWKClient(
                self.jwks_url, cache_jwk_set=True, lifespan=300
            ).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except Exception as exc:
            raise JWTAuthError("token validation failed") from exc
        if claims.get("azp") not in self.authorized_parties:
            raise JWTAuthError("authorized party denied")
        roles = set(claims.get("realm_access", {}).get("roles", []))
        if not self.required_roles.issubset(roles):
            raise JWTAuthError("required role denied")
        scopes = set(str(claims.get("scope", "")).split())
        if not self.required_scopes.issubset(scopes):
            raise JWTAuthError("required scope denied")
        if (
            self.required_environment is not None
            and claims.get("environment") != self.required_environment
        ):
            raise JWTAuthError("environment denied")
        business_units = set(claims.get("business_units", []))
        if (
            self.required_business_unit is not None
            and self.required_business_unit not in business_units
        ):
            raise JWTAuthError("business unit denied")
        campaigns = set(claims.get("campaigns", []))
        if (
            self.required_campaign is not None
            and self.required_campaign not in campaigns
        ):
            raise JWTAuthError("campaign denied")
        if (
            claims.get("typ") == "Bearer"
            and not claims.get("business_units")
            and not claims.get("client_id")
            and not claims.get("azp")
        ):
            raise JWTAuthError("business-unit or service-account claim required")
        return claims
