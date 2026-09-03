# Kong route/plugin read-only reconciliation

Date: 2026-09-03
Target: `65.109.65.169`
Access: loopback Kong Admin API through `codestra-app`; GET only.

## Aggregate read-back

- Routes returned: `29`
- Route plugins returned: `125`
- Routes without any route-scoped plugin: `1` (`codestra-mail-api`)
- Routes with JWT authentication: `7`
- Routes with key-auth authentication: `14`
- Routes with no route-scoped authentication plugin: `8`
- Routes with rate-limiting: `25`
- Routes without rate-limiting: `4`
- Routes with correlation-id: `9`
- Routes with request-size-limiting: `19`

The route inventory is complete at 29/29, but this read-back does not prove
that global plugins, service authentication, upstream correctness, tenant
claims, or authorization scopes satisfy the route contract. The unauthenticated
and no-rate routes require explicit public/standby justification; the mail API
route has no route-scoped controls at all.

KONG_ROUTES_RECONCILED=29/29
KONG_API_ALIGNMENT=FAIL
AUTH_MISMATCH=UNRESOLVED
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
