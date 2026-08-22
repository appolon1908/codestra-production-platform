# Final control-plane certification — production candidate

Date: 2026-08-22. Safety posture: no dialing, hopper loading, carrier traffic, customer calls, SMS, email, callbacks, or transcription was enabled.

## Outcome

The source candidate implements the normalized canonical registry, immutable Codestra UUIDs, desired/actual separation, state/version guards, transactional job/outbox creation, idempotency, explicit command/event/result semantics, dead letters, reconciliation/drift policy, metrics, Kong route/scope policy, stateless modular n8n workflows, a restricted adapter contract, and an Odoo reconciliation dashboard projection.

The candidate is **not certified for protected production cutover**. Local and isolated gates pass, but authoritative-source provenance is incomplete for the deployed Odoo, n8n, and provisioning components; the dependency audit reports vulnerabilities in the host Python environment; no independent protected-branch review/merge exists; and authoritative destination read-back for `TEST_SYN`, agent `synthetic.agent.test.syn.6101`, and extension `6101` has not completed. Accordingly no production migration, mapping-authority cutover, VICIdial mutation, or false `SYNCED` state was performed.

## Evidence summary

- Live read-only Odoo counts: 105 campaigns, 102 legacy mappings, one VICIdial projection, seven identity links, one extension assignment.
- All 105 campaigns were draft/inactive during inspection.
- Mapping difference classification: `RLP-INBOUND-IN` and `TRX-INBOUND-IN` intentionally unmapped generic placeholders; `CMP-400-COD` certification-only; unexplained differences: zero.
- Isolated PostgreSQL: 17 relations created; runtime/owner roles have no login, superuser, createdb, createrole, or bypass-RLS privileges.
- Isolated replay: same command returned same job; stale result rejected and job state unchanged.
- Tests: 226 passed and 9 subtests passed.
- Secret scan: no leaks found.
- Dependency audit: failed with 26 advisories across host-installed `pyjwt`, `python-multipart`, and `starlette`; these are not pinned by this checkout, but the release gate remains failed until the deploy image/SBOM is audited and remediated.

## Production-blocking findings

1. Deployed Odoo and provisioning repositories have no configured origin; the deployed n8n directory is an unborn repository. `AUTHORITATIVE_SOURCE=FAIL`.
2. `TEST_SYN` has no Odoo desired agent-membership row. Keycloak, VICIdial, and Asterisk destination read-back is incomplete. `TEST_SYN_FULL_MAPPING=FAIL`.
3. The one Odoo VICIdial projection currently says active while business telephony intent is false. It is not accepted as actual state; restricted adapter read-back is required before remediation.
4. No independent reviewer has approved or merged this candidate. `REVIEW=PENDING`, merge SHA is unset.
5. Restart, failure-recovery, complete Kong negative matrix, shadow mismatch, and protected production-candidate tests have not been run against the new deployed candidate.

## Certification decision

`FINAL_STATUS=BLOCKED` for production, with implementation and isolated validation complete enough for independent review and a protected staging deployment. The block is intentional and fail-closed; it is not reported as PASS merely because APIs returned success.
