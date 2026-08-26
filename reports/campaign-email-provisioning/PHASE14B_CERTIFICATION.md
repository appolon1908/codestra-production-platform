# Phase 14B campaign email provisioning certification

Evidence date: 2026-08-22. Source baseline: `55810b548661dc33834d3f46e4940089941fa4e8`.

## Outcome

Source hardening is implemented and its local regression suite passes. Production activation remains blocked. No campaign mapping, shared address, personal mailbox, inbound route, sender authorization, or live email was created.

## Runtime inventory

- Odoo campaigns: 105; active: 0.
- Active employees: 5.
- Campaign-agent relationships: 0.
- Expected personal mailboxes under the approved active-agent rule: 0.
- Active campaign-domain mappings: 0.
- Verified domains: 0 of 14.

The complete campaign review table is `CAMPAIGN_EMAIL_MAPPING_REVIEW.csv`. It uses exact tenant proposals only for COD and MBL and marks every row blocked pending explicit campaign approval; it does not activate mappings from name similarity.

## Source controls completed

- Dedicated Odoo email roles and record rules bind mailbox, message, campaign, company, tenant, user, and lifecycle state.
- Canonical Keycloak issuer enforcement and tenant-separated short-lived token caching.
- Dedicated mTLS client identity requirement and protected secret-file permissions.
- Pinned Klyrow private endpoint, exact-recipient routes, no catch-all, and tenant/correlation/idempotency propagation.
- Fail-closed provisioning, explicit address collision, exact sender authorization, validation-before-ACTIVE, and suspension revocation.
- Existing authoritative Keycloak-subject binding, grant/revocation readback, Klyrow mailbox/route/sender readback, and final Odoo ACTIVE/failed projection.
- Exact-recipient Postal inbound processing with Message-ID/thread preservation and fail-closed attachment scan/quarantine.
- The current merged-release test totals are recorded in `PRODUCTION_API_COMMUNICATION_REVIEW_20260822.md` and CI.

## Activation blockers

- All 105 runtime campaigns are inactive and have no assigned agents; campaign owners have not approved exact domain mappings.
- No domain has the complete ownership, MX, SPF, unique DMARC, domain-specific Postal DKIM, TLS, alignment, Postal registration, Klyrow ownership, exact inbound route, and outbound authorization evidence set.
- `codestra.co` publishes conflicting DMARC records. Several domains lack MX/SPF; provider-generated DKIM records are unavailable and must not be guessed.
- No DNS publication authority, production mTLS identity/service authorization evidence, protected PR approval, immutable signed image, isolated deployment, live inbound/outbound canary, or one-hour soak is available.

## Safe next action

Obtain exact campaign-owner approval for one active campaign/domain pair and the provider-generated DNS record set. Publish and verify only that domain, then deploy the reviewed protected image to isolation before creating the three shared exact-recipient routes and one agent canary mailbox.
