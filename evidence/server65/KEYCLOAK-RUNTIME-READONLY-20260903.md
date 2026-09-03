# Keycloak runtime read-only refresh

Date: 2026-09-03
Target: `65.109.65.169` Keycloak container; container-network GETs only.

## Process and OIDC read-back

- Management liveness `/health/live`: `200`
- Management readiness `/health/ready`: `200`
- Management startup `/health/started`: `200`
- OIDC discovery: `200`
- JWKS endpoint: `200`
- Issuer: `https://auth.codestra.co/realms/codestra`
- Discovery advertises PKCE methods: `plain`, `S256`
- Discovery advertises `authorization_code` and `client_credentials`, but also
  legacy/less-restrictive grant and response types including `password` and
  `implicit`.

This proves process health and public metadata only. Client-specific PKCE
enforcement, audience validation, service-account separation, role/scope
mapping, tenant claims, MFA, logout/refresh policy, and session expiry remain
uncertified. The advertised legacy flows require security-owner review before
the identity gate can pass.

KEYCLOAK_PROCESS_HEALTH=PASS
OIDC_DISCOVERY=PASS
JWKS=PASS
KEYCLOAK=FAIL
AUTH=FAIL
TENANCY=FAIL
RBAC=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
