# One-call execution checkpoint — 2026-09-04

## Decision

**NO-GO for the controlled call and NO-GO for limited production.**

This checkpoint records repository/file inspection and source-only template
validation. It is not live runtime evidence, a signed authorization, a backup
certificate, or a completed call report. No runtime mutation or call was issued
by this session. Current runtime flags and counters were not read back.

## Inspected sources

- Platform repository: `appolon1908-hue/codestra-production-platform`.
- Observed base branch: `release/production-activation`.
- Observed base commit: `e44decce67b8bc292753d77a82ca21c9fa37af0f`.
- `reports/app-server-a/PRODUCTION_CALLING_READINESS_20260904.md` at that commit.
- `AGENTS.md`, `CODEX_APP_SERVER_A.md`, the campaign provisioning and restricted
  adapter contracts, and the VICIdial/Odoo mapping specification.
- Saved `VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.md` supplied through
  the user's file library. Its call resources and named approvals are blank.
- `operations/canary/validate-authorization.py`: the existing operational
  validator consumes a protected authorization environment file, not this
  Markdown example. No operational validator or signed-environment check was
  executed against a server in this session.
- SentinelX discovery returned `ok=true`, `hosts=[]`, `count=0`. This means no
  host was available through this session's connector; it does not establish
  that the servers are down.

The repository report records an assessment at `2026-09-04T22:00Z` with
`111 passed, 9 subtests passed`, healthy application components, private Server B
reachability, and `ENABLE_VICIDIAL_WRITES=false` / `SEND_EVENTS=false`.
These are the report's observations, not fresh checks performed in this session.
The same report explicitly blocks production dialing on the missing signed
package and has no reconciled pilot call.

## Requested execution steps

| Step | Session result | Remaining gate |
|---|---|---|
| 1. Complete authorization | PARTIAL: prepared an unsigned fail-closed example; actual private package not completed or changed | Exact pilot resources, controlled destination, window, policy evidence, current runtime source/digests, and named approvals |
| 2. Fresh backups and rollback | NOT_RUN | Server access; paired consistent backup manifests, off-host integrity, isolated restore and rollback proof |
| 3. Final preflight | NOT_RUN | Fresh mapping, policy/idempotency, route/authentication, adapter read-back, consent/DNC/window, monitoring and kill-switch evidence |
| 4. Minimum scoped flags | NOT_RUN | All authorization and preflight gates must pass before any arming |
| 5. One manual call | NOT_RUN | No approved destination/window and no connected execution host |
| 6. End-to-end reconciliation | NOT_RUN | No call issued; no new call/correlation/event/Odoo IDs exist for this attempt |
| 7. Restore flags and decide | NO_GO | No flags were changed by this session; actual fail-closed read-back remains unverified |

Do not describe the earlier conditional pilot readiness as present permission
to dial. Do not mark a restored runtime state PASS merely because this session
made no changes.

## Repository changes

1. Added `VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.example.md`, retaining
   the saved form's 14 sections and adding detailed preflight, reconciliation,
   and disarm evidence fields. Historical source pins, event counts, approvals,
   and PASS defaults are not promoted to current facts.
2. Added explicit release approval alongside business, compliance/privacy,
   security, operations, telephony, Odoo, n8n, and rollback approvals.
3. Kept manual-only / one-attempt limits and all requested capability exclusions;
   added explicit customer-list, unrelated-campaign, and retry denial.
4. Added the private runtime package filename and its backup copies to
   `.gitignore`. Existing ignore rules were preserved. This reduces accidental
   commits; it is not an access-control boundary and cannot stop `git add -f`.
5. Added seven source-only regression tests. No workflow, runtime configuration,
   deployment manifest, source lock, service, or live flag was modified.

The `.example.md` is not a machine authorization and does not replace the
existing protected authorization validation or Server A/Server B approval
handshake. Do not overwrite a newer signed private package with it. Complete
and sign the actual private package only through the existing approved process.

## Local validation performed

```text
python -m unittest discover -s tests -p test_one_call_authorization_template.py -v
Ran 7 tests
OK
```

Checks cover unique keys/no preapproved results, blocked decisions, one manual
attempt and capability exclusions, uninvented targets/policies, all nine named
approval roles, unclaimed preflight/reconciliation, and real Git ignore behavior
for the private package and backup copies while allowing the example.

This is not a re-run of the platform's full regression suite, remote GitHub CI,
backup validation, legal/compliance review, signature verification, or a live
integration test. Full CI status must be read from the resulting PR.

## Required evidence before resuming

The exact campaign/list, agent/extension, controlled destination and ownership,
caller ID/trunk control, and approved window must be supplied in the protected
package. Obtain current consent, DNC, and recording-policy evidence; do not infer
these from possession of a test number or from this execution request. All named
approvals must bind the same finalized manifest and exact runtime artifacts.
Keep destinations, fingerprints, credentials, signatures, and private policy
contents out of repository and CI evidence.

Restore a permitted execution connection to Server A and Server B, or use the
existing approved protected runner. The `production-activation.yml` workflow
supports guarded preflight/backup operations but requires a verified protected
source/image tuple and approved change window; no workflow was dispatched here.
Capture fresh backups and isolated restore/rollback evidence, then run every
preflight gate. Any unknown or failed gate keeps the call blocked.

If subsequently authorized, enforce the single attempt at the point of dialing,
with no retries or route fallback and a verified expiry/kill switch. Disarm on
call completion, expiry, failure, uncertainty, or monitoring loss, before waiting
for asynchronous reconciliation. Reconcile read-only without replaying historical
events. Limited production remains a separately signed release decision.
