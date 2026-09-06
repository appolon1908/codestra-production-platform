# Server 65 Keycloak runtime read-back

Captured read-only at `2026-09-02T17:08:00Z` from the production public identity endpoint. No credentials, tokens, secrets, user records, or private key material were requested or recorded.

Target: `65.109.65.169` identity boundary

Public authority: `https://auth.codestra.co/realms/codestra`

## Direct runtime observations

| Gate | Result | Evidence |
|---|---|---|
| OIDC_DISCOVERY | PASS | HTTPS discovery returned a valid document. |
| ISSUER | PASS | Exact issuer was `https://auth.codestra.co/realms/codestra`. |
| JWKS | PASS | Advertised JWKS URI returned two keys: one RS256 signing key and one RSA-OAEP encryption key. Only public key metadata was inspected. |
| PKCE_S256_ADVERTISED | PASS | Discovery advertises `S256`. Client-level enforcement still requires authenticated configuration read-back. |
| LOGOUT_ENDPOINT | PASS | Discovery advertises the realm OIDC logout endpoint. |
| PUBLIC_DNS | PASS | Public A lookup returned only `65.109.65.169`; no AAAA record was returned. |
| AUTHORITATIVE_DNS | PASS | Both authoritative servers, `ns25.domaincontrol.com` and `ns26.domaincontrol.com`, returned only `65.109.65.169`. |
| HTTPS_PEER | PASS | The discovery request connected directly to `65.109.65.169:443` and returned HTTP 200. |
| TLS | PASS | With DNS and peer identity established, the certificate CN is `auth.codestra.co`; validity is 2026-08-20 through 2026-11-18; SHA-256 fingerprint is `87:5B:F8:40:6E:9B:23:10:20:18:85:C6:D3:F8:B0:39:52:2F:16:37:C0:07:46:0B:68:40:04:B4:42:B3:15:40`. |

## Gates not certified by public read-back

These remain fail-closed until an approved authenticated runtime read-back or bounded test proves them:

| Gate | Result | Required evidence |
|---|---|---|
| AUDIENCE | FAIL | Issued-token audience validation for each production client. |
| PKCE_CLIENT_ENFORCEMENT | FAIL | Effective production client configuration showing S256 enforcement. |
| SERVICE_ACCOUNTS | FAIL | Effective client isolation, credential rotation, and bounded client-credentials tests. |
| ROLE_MAPPING | FAIL | Effective roles/scopes and allow/deny tests. |
| TENANT_CLAIMS | FAIL | Issued-token claim validation plus cross-tenant denial. |
| MFA | FAIL | Effective required-action/authentication-flow read-back and bounded login test. |
| SESSION_CONTROLS | FAIL | Effective access, refresh, idle, maximum-session, logout, and revocation tests. |

The discovery document advertises both `plain` and `S256` server capabilities. This does not prove that production public clients require S256, so the client-enforcement gate remains FAIL.

## Safe commands used

Only public and authoritative DNS lookups, unauthenticated `GET` requests to discovery/JWKS, an HTTPS peer-address read-back, and a TLS certificate handshake were used. Responses were reduced to DNS addresses, endpoint names, supported protocol features, public JWK metadata (`kid`, `kty`, `alg`, `use`), and certificate metadata.

No production state changed.
