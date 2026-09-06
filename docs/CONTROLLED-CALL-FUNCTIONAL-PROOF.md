# Controlled-call functional proof

**Status: BLOCKED / NOT_TESTED. No actual pilot proof is supplied by this change.**

A green source suite, healthy container, signed image, syntactically complete
authorization file, or checksum-valid evidence archive is not a certified call.
No runtime is queried and no call is placed by these source changes.

## Three independent closure requirements

| Gate | Evidence needed to close it |
|---|---|
| Controlled destination authorization | Current independently verified approval, approver authority, exact campaign/list/agent/extension/trunk and controlled destination, caller-ID approval, bounded one-call window, operator and emergency/rollback ownership |
| Business/compliance policy | Exact calling-hours, consent, DNC and recording policy references, destination-owner confirmation, valid zero-match approval and any required runtime policy readback |
| End-to-end pilot reconciliation | The same authorized call linked through the actual Asterisk/VICIdial call identifier, middleware event/correlation identifiers and normalized Odoo record, with matching campaign scope and terminal result |

The completed chain must come from authenticated system readbacks, not copied
example identifiers, hand-entered PASS fields, synthetic unit-test fixtures,
or proof copied from another environment or previous approval window.

Before executing the approved one manual call, preserve the existing source and
image identity, readiness, monitoring, backup/restore and rollback gates. After
it, retain the exact identifiers, timestamps and record counts in protected
evidence; verify no duplicate call or Odoo record and no unrelated callback,
transfer, email or SMS effect. Verify the required disabled-state restoration.
No raw destination, secret or recording content belongs in Git.

## What these scripts actually prove

`operations/canary/validate-authorization.py` checks required fields, one-call
scope and time bounds. Exit 0 means **SCOPE_VALIDATED**, not authentic signature,
permission to activate or evidence of execution. The input's
`SIGNED_CANARY_APPROVAL=VALIDATED` is an external attestation that this parser
cannot independently authenticate. Its output explicitly reports
`signature_authenticity=NOT_VERIFIED`, `activation_authorized=false` and
`business_flow_certified=false`.

`operations/canary/create-blocked-evidence.py` creates a local NOT_RUN record.
It does not query runtime flags, monitoring, call counters or historical events.
Rollback, cleanup and post-call disable therefore remain **NOT_RUN**, not PASS.
Global call attempts remain **UNKNOWN**; zero applies only to this non-dialing
tool. Its generated verifier checks package integrity and blocked-state labels,
not signatures or runtime truth. A checksum cannot establish provenance.

The existing authoritative scope template remains
`operations/canary/canary-authorization.env.example`. Keep completed approval
material in protected operator storage. Do not generate signatures or fill
unknown details to make these checks green. Keep all live effects disabled
until the separate protected activation path accepts the real approval and
preflight evidence. A later persistent-production authorization is separate
from the one-call pilot.
