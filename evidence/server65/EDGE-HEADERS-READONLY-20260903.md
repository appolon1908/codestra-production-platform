# Server 65 edge security-header read-only probe

Date: 2026-09-03
Endpoint: `https://api.breero.com/health`
Request: unauthenticated GET only; no body or external effect.

Response status was HTTP `503`, but the response included:

- HSTS with `includeSubDomains`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- restrictive Permissions-Policy
- strict-origin referrer policy
- Caddy and Kong request identifiers
- correlation ID
- rate-limit headers

No authorization or API-key header was returned. This is a positive header
read-back only; it does not prove access-log redaction, application health, or
readiness.

EDGE_SECURITY_HEADERS=PASS
EDGE_SECRET_REDACTION=UNPROVEN
EDGE_HEALTH=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
