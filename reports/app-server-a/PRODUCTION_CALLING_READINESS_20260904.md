# Odoo-to-VICIdial production calling readiness

Assessment basis: uploaded terminal transcript dated 2026-09-04T22:00Z and
repository inspection at PR #263 source 3a040386925c36f43c2a253fe98c52d54881bf81.
This is a repository record, not a fresh server audit or retrieval of the
server's original untracked report. Existing server working trees were untouched.

**Decision: BLOCKED. The actual business flow is not certified.**

| Gate | Status | Evidence boundary |
|---|---|---|
| Controlled destination authorization | BLOCKED | No current completed and independently verified one-call authorization was supplied |
| Business/compliance policy | BLOCKED | Exact current campaign, calling-hours, consent, DNC and recording approval remain unverified |
| End-to-end pilot reconciliation | NOT_TESTED | No authenticated chain linking VICIdial call ID, middleware correlation/event IDs and Odoo record |
| Live 8095 health/readiness readback | NOT_TESTED | Transcript reported 404; no server probe was rerun by this repair |
| Middleware deployment identity / restore / rollback | NOT_TESTED | Source/image candidate evidence does not establish runtime certification |
| Repository evidence-honesty regression | PASS | 22 tests and 2 subtests passed locally; no call was made by these tests |

The uploaded transcript's 110 tests and 9 subtests are historical results, not
functional proof of a completed call. Prepared release/probe changes from the
broader four-gap work are not represented here as published or deployed fixes.

The same historical transcript recorded the canonical middleware probe results
below. They document that earlier observation only; this repair did not rerun
the probes and does not treat them as current runtime certification.
The transcript classified the earlier 404 as a
"false alarm caused by diagnostic path mismatch" after the canonical suffixed
probes succeeded.

```text
200 http://127.0.0.1:8095/healthz
200 http://127.0.0.1:8095/readyz
200 http://127.0.0.1:8095/livez
```

This focused patch makes the scope checker report SCOPE_VALIDATED rather than
implying authentic signature verification, adds missing extension/policy/rollback
references, rejects duplicate/malformed fields, and removes unsupported PASS
claims from the blocked-evidence generator. Unknown global call counts, runtime
flags and monitoring state remain unknown. Package checksums prove integrity
only, never actual execution or signer authority.

See docs/CONTROLLED-CALL-FUNCTIONAL-PROOF.md. The completed one-call approval and
authenticated runtime readbacks are still required. No dialing, email, SMS,
callback, transfer or production deployment was performed by this repair.
