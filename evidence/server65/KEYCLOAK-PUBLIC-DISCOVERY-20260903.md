# Server 65 Keycloak public discovery refresh

Captured read-only: 2026-09-03
Target identity authority: `https://auth.codestra.co/realms/codestra`

The HTTPS discovery document returned successfully. Observed public metadata:

- issuer: `https://auth.codestra.co/realms/codestra`
- JWKS URI: `https://auth.codestra.co/realms/codestra/protocol/openid-connect/certs`
- advertised code challenge methods: `plain`, `S256`
- logout endpoint: `https://auth.codestra.co/realms/codestra/protocol/openid-connect/logout`
- JWKS public key metadata: one `RS256` signing key and one `RSA-OAEP`
  encryption key (only `kid`, `kty`, `alg`, and `use` inspected)

This does not certify effective client PKCE enforcement, audiences, service
account isolation, roles/scopes, tenant claims, MFA, or session controls. Those
remain fail-closed pending approved authenticated runtime read-back.

No credentials, tokens, private key material, user records, or secret values
were requested or recorded. `SSH_CHANGED=NO`; `PRODUCTION_CHANGED=NO`.
