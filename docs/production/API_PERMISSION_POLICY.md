# Production API permission policy

Status: `UNIMPLEMENTED_BLOCKED_PENDING_EXECUTABLE_ENFORCEMENT`

Policy reference: `CODESTRA-API-PERMISSIONS-V1`

Production machine access is default-deny. Separate identities are required for
read-only inventory, reporting, lead/list preparation, disposition updates, and
controlled writes. No application container may contain an administrator
credential. Credentials must be short-lived where supported and machine
identities must use mTLS with an independently validated subject, SAN, issuer,
validity, key usage, revocation state, owner, and mount path.

Authorization binds client identity, tenant, campaign, role, scope, operation,
and environment. Unknown or mismatched values are denied before an adapter or
database operation. Controlled writes additionally require an idempotency key,
correlation ID, change reason, approved feature flag, and audit record.

Required test matrix:

| Case | Expected |
|---|---|
| Correct identity, tenant, campaign, role and scope | Allow only the named operation |
| Missing/expired/revoked certificate | Deny |
| Unknown client, role, tenant, campaign or scope | Deny |
| Cross-tenant or cross-campaign request | Deny |
| Read identity attempts a write | Deny |
| Missing idempotency key, correlation ID or reason | Deny |
| Production feature flag false | Deny |
| Broad administrator credential detected in a container | Gate failure |

Approval intent is recorded in the current activation packet. It is not a
signature or production authorization.

This document is a proposed policy specification, not implementation evidence.
The production gate remains blocked until runtime enforcement and the complete
positive and negative matrix are independently verified.
