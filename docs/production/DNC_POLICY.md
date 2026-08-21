# Production do-not-call policy

Status: `UNIMPLEMENTED_BLOCKED_PENDING_EXECUTABLE_ENFORCEMENT`

Policy reference: `CODESTRA-DNC-CONSENT-V1`

The decision is deny unless current, authoritative evidence positively permits
the exact tenant, campaign, destination, purpose, jurisdiction, and time. A
missing consent record, unknown status, unavailable policy service, stale
decision, tenant/campaign mismatch, or replayed decision is denied.

Emergency, premium-rate, prohibited, and unauthorized international
destinations are always blocked. Decisions carry a short expiry, unique nonce,
policy version, normalized destination hash, and audit correlation ID. Raw
destinations and personal data are excluded from repository evidence.

Required test matrix:

| Case | Expected |
|---|---|
| Current explicit consent and permitted policy | Allow policy decision only |
| Listed DNC destination | Deny |
| Missing consent or unknown status | Deny |
| Policy service unavailable or timeout | Deny |
| Emergency, premium or prohibited destination | Deny |
| Unauthorized international destination | Deny |
| Tenant/campaign mismatch | Deny |
| Expired or replayed decision | Deny |
| Audit write unavailable | Deny |

This policy does not authorize PSTN dialing, which remains separately governed
and disabled.

This document is a proposed policy specification, not implementation evidence.
The production gate remains blocked until runtime enforcement and the complete
positive and negative matrix are independently verified.
