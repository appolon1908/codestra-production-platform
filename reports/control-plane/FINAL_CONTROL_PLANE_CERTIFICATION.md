# Final control-plane certification — production candidate

Date: 2026-08-22. Safety posture: no dialing, hopper loading, carrier traffic, customer calls, SMS, email, callbacks, or transcription was enabled.

## Outcome

The source candidate implements the normalized canonical registry, immutable Codestra UUIDs, desired/actual separation, state/version guards, transactional job/outbox creation, idempotency, explicit command/event/result semantics, dead letters, reconciliation/drift policy, metrics, Kong route/scope policy, stateless modular n8n workflows, a restricted adapter contract, and an Odoo reconciliation dashboard projection.

The candidate is **not certified for authoritative production cutover**. Protected source provenance has been recovered and the isolated candidate is deployed, but no independent protected-branch review/merge exists, the isolated staging VICIdial client certificate is stale, the Odoo command/dashboard addon has not been cut over, and authoritative Asterisk extension read-back has not completed. Accordingly no production mapping-authority cutover, VICIdial mutation, or false `SYNCED` state was performed.

## Evidence summary

- Live read-only Odoo counts: 105 campaigns, 102 legacy mappings, one VICIdial projection, seven identity links, one extension assignment.
- All 105 campaigns were draft/inactive during inspection.
- Mapping difference classification: `RLP-INBOUND-IN` and `TRX-INBOUND-IN` intentionally unmapped generic placeholders; `CMP-400-COD` certification-only; unexplained differences: zero.
- Deployed Odoo, provisioning, and n8n source snapshots were recovered to protected remote archive branches; the middleware candidate is commit `11268120532c4fff7ac42c2e6354ebcfeb305f36`.
- Isolated PostgreSQL: 17 relations created; runtime/owner roles have no login, superuser, createdb, createrole, or bypass-RLS privileges. The shadow registry contains all 105 campaigns, zero telephony-enabled campaigns, 105 durable jobs, and 105 outbox events; no dispatcher was enabled.
- Isolated replay: same command returned same job; stale result rejected and job state unchanged.
- Isolated middleware restart preserved all 105 campaigns/jobs and returned ready. The production n8n restart preserved 23 activation states and removed all authoritative workflow static data.
- Restricted-adapter mTLS read-back: `TEST_SYN` exists and is inactive (`active=N`); `cod00016` exists, is active, and belongs to `WEBTEST_SYN`. Read-only inventory reports 25 campaigns before and after this mission.
- Tests: 236 passed and 9 subtests passed; restricted-adapter suite: 40 passed.
- Secret scan: no leaks found.
- Candidate-image dependency audit: zero known Python package vulnerabilities after pinning pip 26.2.

## Production-blocking findings

1. `TEST_SYN` still has no Odoo desired agent-membership row and the new Odoo outbox/dashboard addon has not been deployed. Asterisk endpoint 6101 read-back is incomplete. `TEST_SYN_FULL_MAPPING=FAIL`.
2. The isolated staging adapter certificate is rejected by the gateway CA. Read-back succeeded using the currently approved production middleware certificate with read-only scopes; issuing a distinct valid staging machine certificate remains required.
3. The legacy statement that VICIdial contained one campaign conflicts with the authoritative adapter inventory of 25. The mission performed no VICIdial writes; this discrepancy must be classified before any provisioning plan can be approved.
4. The one Odoo VICIdial projection says active while authoritative VICIdial read-back says inactive. This is confirmed drift and must be corrected through the Odoo projection/reconciliation path, not by changing VICIdial.
5. No independent reviewer has approved or merged this candidate. `REVIEW=PENDING`, protected merge SHA is unset.
6. A real isolated Kong/Keycloak negative matrix and full Odoo → Kong → middleware → n8n callback trace remain incomplete.

## Certification decision

`FINAL_STATUS=BLOCKED` for production, with implementation and isolated validation complete enough for independent review and a protected staging deployment. The block is intentional and fail-closed; it is not reported as PASS merely because APIs returned success.
