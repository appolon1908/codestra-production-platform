# Codestra Synthetic Call Gate Authorization for Codex

## Purpose

Resolve the current production-readiness blocker by authorizing a tightly bounded set of synthetic telephony calls that create new finalized `call_ended` records after the approved production watermark.

This authorization supplements:

`CODESTRA_PRODUCTION_READINESS_AND_STAGED_CUTOVER_AUTHORIZATION.md`

It does not replace that document and does not authorize unrestricted live production activation.

---

# 1. Authorization

```text
CHANGE_ID=CHG-20260725-SYNTHETIC-CALL-GATE-01
APPROVER=Ralph L. Appolon
APPROVAL_DATE=2026-07-25

ROOT_ENGINEERING_AUTHORIZED=YES
AUTONOMOUS_EXECUTION_AUTHORIZED=YES
SYNTHETIC_TEST_CALLS_AUTHORIZED=YES
MAXIMUM_SYNTHETIC_CALLS=10
MINIMUM_SYNTHETIC_CALLS=5
CUSTOMER_DESTINATIONS_AUTHORIZED=NO
PREDICTIVE_DIALING_AUTHORIZED=NO
CARRIER_CONFIGURATION_CHANGES_AUTHORIZED=NO
PUBLIC_DID_CHANGES_AUTHORIZED=NO
HISTORICAL_EVENT_REPLAY_AUTHORIZED=NO
EXTERNAL_CUSTOMER_MESSAGES_AUTHORIZED=NO
```

Codex may originate or receive only the bounded synthetic calls required by this document.

---

# 2. Server Roles

## Server A

- Public IP: `65.109.65.169`
- Private IP: `10.40.0.1`
- Owns the production-readiness controller, middleware, PostgreSQL integration state, Odoo canary, n8n canary, monitoring, evidence, and cutover gates.

## Server B

- Public IP: `65.21.67.207`
- Private IP: `10.40.0.2`
- Owns VICIdial, Asterisk, finalized call records, the production worker, local queue, checkpoint, and passive event publication.

---

# 3. Current Protected State

Before beginning, confirm:

```text
NEW_FINALIZED_TOTAL=0
QUARANTINED=1110
PRODUCTION_PENDING=0
SYNC_ENABLED=disabled
SYNC_ACTIVE=inactive
SEND_EVENTS=false
KILL_SWITCH=active
```

The 1,110 quarantined legacy events must remain quarantined and production-ineligible.

Do not begin when any historical event is eligible for the production worker.

---

# 4. Allowed Synthetic Call Scope

Use only:

- dedicated synthetic test agents;
- inactive test campaigns;
- test-only DIDs;
- test queues;
- non-customer destinations;
- internal extensions;
- approved loopback or isolated SIP test endpoints;
- approved test trunks that cannot reach customer destinations;
- test recording storage;
- synthetic caller identity and metadata.

Do not use:

- real customer phone numbers;
- customer leads;
- production lead lists;
- predictive dialing;
- production campaign traffic;
- public customer-facing DIDs;
- real customer voicemail;
- real customer recordings;
- emergency numbers;
- premium-rate numbers;
- international destinations unless they are dedicated test endpoints;
- any destination that could create a charge or customer interaction without prior verification.

---

# 5. Required Scenario Matrix

Create between five and ten calls.

Cover as many of these as the isolated test environment supports:

1. Outbound answered call.
2. Outbound no-answer call.
3. Outbound busy or rejected call.
4. Inbound answered call.
5. Inbound abandoned or unanswered call.
6. A second call with the same-second timestamp as another call, or an equivalent deterministic-order fixture.
7. A call observed across a controlled worker restart.
8. A call that validates recording-reference exclusion or synthetic recording handling.
9. A duplicate event delivery attempt.
10. A controlled downstream retry.

At minimum, the completed set must include:

- one outbound answered;
- one outbound non-answered;
- one inbound answered;
- one inbound non-answered;
- deterministic ordering coverage;
- restart/checkpoint coverage.

When the installed test environment cannot safely create one scenario, mark it as `BLOCKED_TEST_FIXTURE` and do not substitute a customer call.

---

# 6. Preconditions

Before any call:

- verify both project-local locks;
- verify the authorization document checksum;
- verify the hard starting watermark;
- verify the legacy queue quarantine;
- verify the worker selects only records later than the watermark;
- verify the synthetic campaign and agent are production-ineligible;
- verify the destination allowlist;
- verify the test DID and queue are isolated;
- verify no public customer route can be selected;
- verify active production calls and channels;
- verify Asterisk and VICIdial health;
- verify the emergency kill switch;
- verify downstream Odoo and n8n canary scope;
- verify external customer communication remains disabled;
- verify monitoring is active;
- create a fresh checkpoint and rollback reference.

Stop when any precondition is unknown.

---

# 7. Worker Activation Boundary

For the synthetic gate, Codex may temporarily activate only the bounded `call_ended` worker path.

Requirements:

- `call_ended` only;
- new finalized records only;
- hard starting watermark;
- event budget no greater than ten;
- bounded batch size;
- bounded runtime;
- automatic stop after the budget or time limit;
- no boot persistence during this gate;
- no `agent_status` or other event families;
- no historical queue processing;
- no external customer messages;
- no callbacks;
- no telephony-control actions;
- no AI voice;
- no unrelated Odoo or n8n workflow.

The kill switch must remain immediately available.

---

# 8. Downstream Canary Boundary

## Odoo

Permit only the accepted normalized call-record effect.

Require:

- correct business unit;
- correct campaign;
- correct call identifier;
- one logical call result;
- duplicate delivery creates no duplicate result;
- no unrelated customer, lead, opportunity, appointment, campaign, agent, or telephony mutation;
- complete audit;
- source-to-Odoo reconciliation.

## n8n

Permit only one accepted canary workflow.

Require:

- exact workflow code and version;
- bounded activation window;
- no email, SMS, social message, callback, or customer communication;
- idempotency before any effect;
- duplicate input creates no repeated result;
- workflow automatically returns inactive after the gate;
- complete execution evidence.

---

# 9. Monitoring During Calls

Continuously monitor:

- active calls and channels;
- queues and agents;
- endpoint registrations;
- source finalized-row count;
- worker state;
- checkpoint;
- pending and retry queue depth;
- oldest pending age;
- HTTP status distribution;
- TLS and HMAC failures;
- schema failures;
- duplicate and conflict counts;
- Odoo results;
- n8n executions;
- CPU;
- memory;
- disk;
- database health;
- kill-switch state;
- Asterisk and VICIdial health.

Do not proceed to the next call until the previous call is finalized, processed, reconciled, and within all thresholds.

---

# 10. Immediate Abort Triggers

Abort and roll back immediately for:

- any customer destination selected;
- any historical event selected;
- any event before or at the hard watermark;
- any source-table write;
- any unexpected call, agent, queue, campaign, endpoint, or DID mutation;
- any missing finalized event;
- any duplicate business result;
- any sensitive-field leak;
- any checkpoint regression;
- any uncontrolled retry;
- any unexpected Odoo write;
- any unexpected n8n workflow;
- any external customer message;
- any callback;
- any telephony-control action outside creating and ending the authorized synthetic calls;
- any monitoring blind spot;
- any kill-switch failure;
- any Asterisk, VICIdial, MariaDB, Apache, middleware, Odoo, or n8n health degradation;
- any call outside the maximum event budget.

---

# 11. Rollback

On any trigger:

1. Activate the kill switch.
2. Stop the bounded worker.
3. Set `SEND_EVENTS=false`.
4. Keep the persistent service disabled.
5. End only the active synthetic test call when safe and under the approved test procedure.
6. Preserve checkpoint, queue, logs, and evidence.
7. Quarantine uncertain events.
8. Deactivate the n8n canary.
9. Reconcile Odoo results.
10. Verify no historical event moved.
11. Verify no customer communication occurred.
12. Verify telephony health.
13. Restore the prior verified configuration when changed.
14. Release locks normally.
15. Report the exact trigger.

Do not delete failure evidence.

---

# 12. Acceptance Requirements

The synthetic call gate passes only when:

```text
SYNTHETIC_CALLS_PLACED=5_TO_10
CUSTOMER_CALLS_PLACED=0
HISTORICAL_EVENTS_PROCESSED=0
LEGACY_QUEUE_PRODUCTION_ELIGIBLE=0

OUTBOUND_ANSWERED=PASS
OUTBOUND_NONANSWERED=PASS
INBOUND_ANSWERED=PASS
INBOUND_NONANSWERED=PASS
DETERMINISTIC_ORDERING=PASS
RESTART_CHECKPOINT_CONTINUITY=PASS

MISSING_EVENTS=0
DUPLICATE_CANONICAL_EVENTS=0
DUPLICATE_ODOO_RESULTS=0
DUPLICATE_N8N_RESULTS=0
SENSITIVE_FIELD_VIOLATIONS=0
UNINTENDED_ACTIONS=0
RECONCILIATION_GAPS=0

ODOO_CANARY=PASS
N8N_CANARY=PASS
EXTERNAL_CUSTOMER_MESSAGES=0
CALLBACKS_CREATED=0
UNAUTHORIZED_TELEPHONY_ACTIONS=0

WORKER_BOOT_PERSISTENCE=DISABLED
SEND_EVENTS_FINAL=false
KILL_SWITCH_FINAL=active
```

The final fail-closed state remains in force after this synthetic gate.

---

# 13. Resume Existing Staged Cutover

After this gate passes, resume the existing production-readiness authorization at:

1. Five-to-ten new finalized production `call_ended` events when natural production calls become available.
2. One-hour monitored soak.
3. One-business-day monitored soak.
4. Conditional boot persistence for `call_ended` only.

The synthetic gate proves the test scenarios and worker behavior. It does not replace the required natural-production soak unless the approved production-readiness document is formally amended with equivalent evidence.

---

# 14. Required Final Report

Return:

```text
CHANGE_ID=CHG-20260725-SYNTHETIC-CALL-GATE-01
OVERALL_STATUS=

AUTHORIZATION_VERIFIED=
LOCKS=PASS_OR_FAIL
HARD_STARTING_WATERMARK=
LEGACY_QUEUE_QUARANTINED=
LEGACY_QUEUE_PRODUCTION_ELIGIBLE=

SYNTHETIC_CALLS_PLACED=
CUSTOMER_CALLS_PLACED=
OUTBOUND_ANSWERED=
OUTBOUND_NONANSWERED=
INBOUND_ANSWERED=
INBOUND_NONANSWERED=
DETERMINISTIC_ORDERING=
RESTART_CHECKPOINT_CONTINUITY=

NEW_FINALIZED_EVENTS=
HISTORICAL_EVENTS_PROCESSED=
MISSING_EVENTS=
DUPLICATE_CANONICAL_EVENTS=
CHECKPOINT_REGRESSION=

ODOO_CANARY=
ODOO_RESULTS=
DUPLICATE_ODOO_RESULTS=
ODOO_UNRELATED_WRITES=

N8N_CANARY=
N8N_EXECUTIONS=
DUPLICATE_N8N_RESULTS=
EXTERNAL_CUSTOMER_MESSAGES=

SENSITIVE_FIELD_VIOLATIONS=
UNINTENDED_ACTIONS=
UNAUTHORIZED_TELEPHONY_ACTIONS=
CALLBACKS_CREATED=
RECONCILIATION_GAPS=

ROLLBACK_TRIGGERED=
ROLLBACK_RESULT=
WORKER_BOOT_PERSISTENCE=
SEND_EVENTS_FINAL=
KILL_SWITCH_FINAL=

EVIDENCE_DIRECTORY=
CALL_MATRIX_REPORT=
WORKER_REPORT=
ODOO_REPORT=
N8N_REPORT=
RECONCILIATION_REPORT=
ROLLBACK_REPORT=
FINAL_REPORT=
FINAL_REPORT_SHA256=
```

Successful completion result:

```text
OVERALL_STATUS=SYNTHETIC_CALL_GATE_PASS
SYNTHETIC_CALLS_PLACED=5_TO_10
CUSTOMER_CALLS_PLACED=0
HISTORICAL_EVENTS_PROCESSED=0
MISSING_EVENTS=0
DUPLICATE_CANONICAL_EVENTS=0
DUPLICATE_ODOO_RESULTS=0
DUPLICATE_N8N_RESULTS=0
SENSITIVE_FIELD_VIOLATIONS=0
UNINTENDED_ACTIONS=0
RECONCILIATION_GAPS=0
WORKER_BOOT_PERSISTENCE=DISABLED
SEND_EVENTS_FINAL=false
KILL_SWITCH_FINAL=active
```

---

# 15. Paste-Ready Codex Mandate

Proceed autonomously with the bounded synthetic-call gate authorized by this document.

Use full root engineering access on both servers only within this scope.

Do not wait for natural calls during this gate.

Create between five and ten isolated synthetic calls using test-only agents, campaigns, DIDs, queues, endpoints, and non-customer destinations.

Do not use customer records, production lead lists, predictive dialing, public customer DIDs, or unrestricted carrier routes.

Keep all 1,110 legacy events quarantined and production-ineligible.

Temporarily activate only the bounded new-events-only `call_ended` path.

Validate outbound answered, outbound non-answered, inbound answered, inbound non-answered, deterministic ordering, restart continuity, Odoo idempotency, n8n idempotency, monitoring, reconciliation, and rollback.

Do not enable customer communications, callbacks, AI voice, other event families, or boot persistence.

Abort and roll back immediately on any historical selection, customer destination, duplicate effect, missing event, sensitive-field leak, checkpoint regression, unintended action, monitoring failure, or kill-switch failure.

Correct defects autonomously and rerun affected tests.

Finish in the fail-closed state with `SEND_EVENTS=false`, the service not persistent, and the kill switch active.

Return the complete evidence-backed final report.
