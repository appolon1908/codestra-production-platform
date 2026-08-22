# Production recording, consent, and retention policy

Status: `UNIMPLEMENTED_BLOCKED_PENDING_EXECUTABLE_ENFORCEMENT`

Policy reference: `CODESTRA-RECORDING-CONSENT-RETENTION-V1`

Recording is disabled unless an authoritative decision positively permits the
exact jurisdiction, destination, tenant, campaign, purpose, and consent state.
Missing or unavailable policy data fails closed. Consent must be captured and
audited before recording begins and withdrawal must stop future recording.

Recordings require encryption in transit and at rest, least-privilege role and
tenant access, immutable access audit, an approved retention duration, legal
hold support, and a reviewed deletion workflow. Legal hold overrides scheduled
deletion but never grants access. Repository evidence contains references and
hashes only, never recordings or customer data.

Required test matrix:

| Case | Expected |
|---|---|
| Applicable policy, explicit consent, authorized role | Allow scoped access/recording |
| Missing consent, policy, jurisdiction or destination | Disabled/deny |
| Policy service unavailable | Disabled/deny |
| Unauthorized role or cross-tenant access | Deny and audit |
| Expired retention without legal hold | Reviewed deletion workflow |
| Active legal hold | Preserve; access remains role-gated |
| Encryption or audit sink unavailable | Disabled/deny |
| Consent withdrawn | Stop future recording and audit |

Approval intent is not a signature. Recording remains disabled until protected
approval and the complete runtime matrix pass.

This document is a proposed policy specification, not implementation evidence.
The production gate remains blocked until runtime enforcement and the complete
positive and negative matrix are independently verified.
