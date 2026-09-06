# Repository lifecycle

Status: **FAIL — protected owner decisions required**

This document records the lifecycle rule; it does not manufacture authority from repository names or documentation.

| Lifecycle | Meaning | Production eligibility |
|---|---|---|
| CANONICAL | Sole approved source authority for its stated service boundary | Eligible after all protected release gates pass |
| SUPPORTING | Contract, SDK, add-on, infrastructure, or operations source with a canonical consumer | Not an independent application runtime authority |
| ADOPTED_RUNTIME | Source adopted into `codestra-production-runtime-authority` because no maintained canonical source existed | Eligible only with a protected source lock and provenance |
| LEGACY_COMPATIBILITY | Retained solely for an identified compatibility dependency | No new independent production ownership |
| DEPRECATED | Replacement is canonical and rollback retention is complete | No production promotion |
| UNSETTLED | Ownership or overlap has not received protected owner approval | Production blocked |

Transitions require a protected PR, named security and business owners, database and runtime ownership, replacement and rollback evidence, and an updated `SERVICE-OWNER-MATRIX.yaml`. Archival or deletion additionally requires current backup and isolated restore proof.

The five duplicate/overlap decisions remain UNSETTLED:

- `Middleware-` and `Codestra-SRL/codestra-middleware`
- `Odoo` and `Codestra-SRL/codestra-odoo-addons`
- `codestra-backend` and `backend2`
- `Codesrea-Social-` and `social.codestra.co`
- `communication-platform-` and `Codestra-Communication-CC`

Until their protected decisions merge, no member of a pair may silently become an additional production authority.
