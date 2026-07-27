# Codestra Production Readiness and Staged Cutover Authorization for Codex

## Scope

This authorization applies to the authenticated VICIdial-to-Codestra event pipeline and its intended downstream Odoo, middleware, n8n, monitoring, checkpoint, and reconciliation behavior.

It authorizes Codex to complete all remaining production-readiness work and, only after every mandatory gate passes, perform a staged production cutover.

It does not authorize an uncontrolled “turn everything on” action.

It does not authorize:

- predictive dialing activation;
- carrier changes;
- public DID changes;
- campaign activation unrelated to this integration;
- live AI voice;
- customer recording backfill;
- historical event replay;
- arbitrary callbacks;
- external email, SMS, or social delivery outside explicitly accepted workflows;
- firewall or SSH weakening;
- unrelated production changes.

## Authorization

```text
CHANGE_ID=CHG-20260725-VICIDIAL-EVENT-PRODUCTION-CUTOVER-01
APPROVER=Ralph L. Appolon
ROOT_ENGINEERING_AUTHORIZED=YES
AUTONOMOUS_REMEDIATION_AUTHORIZED=YES
STAGED_PRODUCTION_EVENT_CUTOVER_AUTHORIZED=YES
LEGACY_QUEUE_QUARANTINE_AUTHORIZED=YES
BOUNDED_NEW_EVENTS_ONLY_SOAK_AUTHORIZED=YES
DOWNSTREAM_ODOO_CANARY_AUTHORIZED=YES
DOWNSTREAM_N8N_CANARY_AUTHORIZED=YES
EXTERNAL_CUSTOMER_COMMUNICATION_AUTHORIZED=NO
HISTORICAL_REPLAY_AUTHORIZED=NO
UNBOUNDED_ACTIVATION_AUTHORIZED=NO
```

Codex must work autonomously through routine engineering decisions, testing, correction, rollback rehearsal, canary, soak, and final evidence.

Codex must not claim production readiness or enable persistent production operation until every mandatory gate below passes.

---

# 1. Server Assignment

## Server A

- Public IP: `65.109.65.169`
- Private IP: `10.40.0.1`
- Owns middleware ingestion, PostgreSQL integration state, Odoo delivery, n8n, NATS, Temporal, monitoring, feature flags, reconciliation, and release evidence.

## Server B

- Public IP: `65.21.67.207`
- Private IP: `10.40.0.2`
- Owns VICIdial/Asterisk source truth, finalized-source selection, source checkpoint, worker state, local queue/outbox, and passive telephony-event publication.

---

# 2. Current Starting State

Treat the current fail-closed state as the baseline:

```text
codestra-vicidial-sync.service=disabled_inactive
SEND_EVENTS=false
PRODUCTION_READY=NO
```

The authenticated canonical `call_ended` path has passed a bounded single-event canary, but this alone does not prove safe persistent production operation.

Known blockers to resolve:

1. No accepted bounded live soak.
2. Finalized production-source boundary has only design or fixture proof.
3. A legacy queue of 1,110 historical records remains unresolved.
4. Intended downstream Odoo and n8n effects have not been accepted end to end.
5. Production worker regression coverage is incomplete.
6. Production monitoring and alerting are incomplete.
7. A consolidated cutover and rollback runbook is incomplete.
8. Persistent boot operation has not been accepted.

---

# 3. Non-Negotiable Safety Rules

Throughout readiness work:

- no historical record may be transmitted;
- the 1,110 legacy rows must never enter the production worker;
- no event older than the approved starting watermark may be selected;
- no full-table or unbounded source scan is permitted;
- no source-table write is permitted;
- no direct telephony action is permitted;
- no carrier, campaign, lead, list, agent, endpoint, DID, or dialplan mutation is permitted;
- no customer communication is permitted until its specific workflow is accepted;
- no sensitive source fields may be added to the canonical payload;
- no secret may be printed or committed;
- no production flag may be enabled before its matching gate passes;
- a failed test must return to the previous verified fail-closed state;
- evidence must be preserved on failure and rollback.

---

# 4. Project Lock and Change Control

Use a persistent project-local kernel lock for the complete milestone.

## Server A lock root

`/root/codestra-production-completion/.locks`

## Server B lock root

`/root/vicidial-sync-remediation/.locks`

Requirements:

- regular lock file;
- root ownership;
- restrictive permissions;
- no symlink;
- same process holds the lock across each mutation phase;
- contention test;
- automatic release on process exit;
- no deletion, stealing, or bypassing an active lock;
- no waiting interactively while holding a mutation lock.

Before any mutation, record:

- lock path;
- lock owner;
- contention result;
- source revision;
- installed image or package digest;
- configuration hashes;
- service state;
- current feature flags;
- queue counts;
- checkpoint state;
- source watermarks;
- downstream workflow state;
- rollback references.

---

# 5. Phase 1 — Legacy Queue Quarantine

The user explicitly authorizes indefinite quarantine of the 1,110 historical queue records.

Do not delete them.

Do not mark them sent.

Do not transform them into the new canonical production stream.

Required actions:

1. Capture a complete sanitized inventory by event type, age, status, source, and identifier range.
2. Create a protected immutable quarantine manifest.
3. Calculate a payload or row hash for every quarantined record without placing sensitive data in evidence.
4. Assign the records to an explicit legacy quarantine state or physically separate store.
5. Remove the quarantined records from every active worker selection predicate.
6. Introduce a hard minimum production watermark later than every quarantined record.
7. Add automated tests proving that quarantined rows can never be selected, retried, or replayed by the production worker.
8. Add a separate, disabled administrative process for any future reviewed disposition.
9. Prove the production worker sees zero eligible historical records.

Required result:

```text
LEGACY_QUEUE_TOTAL=1110
LEGACY_QUEUE_DISPOSITION=INDEFINITE_QUARANTINE
LEGACY_QUEUE_DELETED=0
LEGACY_QUEUE_REPLAYED=0
LEGACY_QUEUE_PRODUCTION_ELIGIBLE=0
HARD_STARTING_WATERMARK=VERIFIED
```

Stop if any historical row remains production-eligible.

---

# 6. Phase 2 — Live Finalized-Source Boundary Proof

Replace design-only source proof with direct, read-only production proof.

Codex must document the actual source tables, finalization predicates, ordering keys, and tie-break rules.

The selector must be:

- new-events-only;
- finalized-records-only;
- bounded;
- deterministic;
- restart-safe;
- compatible with simultaneous identical timestamps;
- protected against timestamp regression;
- protected against historical scans;
- protected against malformed or oversized fields.

Required proof:

1. Identify the exact finalized condition for outbound calls.
2. Identify the exact finalized condition for inbound calls.
3. Identify non-answered disposition behavior.
4. Define deterministic ordering using a stable tie-breaker.
5. Define the initial high-water mark after quarantine.
6. Test multiple rows with identical timestamps.
7. Test rows becoming finalized after initially being incomplete.
8. Test restart continuity.
9. Test database disconnect and reconnect.
10. Test that no source update occurs.
11. Test that excluded sensitive fields are never selected.
12. Review query plans and indexes.
13. Prove bounded batch and query duration.

Required result:

```text
SOURCE_BOUNDARY_PROOF=PASS_LIVE_READ_ONLY
OUTBOUND_FINALIZED_PREDICATE=PASS
INBOUND_FINALIZED_PREDICATE=PASS
NONANSWERED_DISPOSITION_PREDICATE=PASS
DETERMINISTIC_TIE_BREAKER=PASS
IDENTICAL_TIMESTAMP_TEST=PASS
SOURCE_WRITES=0
HISTORICAL_ROWS_SELECTED=0
```

---

# 7. Phase 3 — Production Worker Regression Suite

Add and pass automated tests against the actual production worker path, not only the fixture harness.

Required coverage:

- simultaneous rows with identical timestamps;
- database disconnect and reconnect;
- crash before HTTP request;
- crash after HTTP request but before local sent-state commit;
- crash after sent-state commit;
- HTTP 202;
- HTTP 401;
- HTTP 403;
- HTTP 409 duplicate and conflict cases;
- HTTP 429;
- HTTP 500 and other retryable 5xx;
- permanent 4xx;
- timeout;
- DNS failure;
- TLS trust failure;
- client certificate failure;
- HMAC failure;
- restart continuity;
- checkpoint corruption;
- checkpoint regression;
- backlog limit;
- batch limit;
- kill switch before start;
- kill switch while running;
- malformed source rows;
- oversized source fields;
- prohibited sensitive source fields;
- local disk pressure;
- downstream unavailability;
- retry storm prevention;
- bounded exponential backoff;
- dead-letter behavior;
- duplicate side-effect prevention.

Every test must record expected and actual results, timestamp, revision, and evidence path.

Required result:

```text
PRODUCTION_WORKER_REGRESSION=PASS
TEST_FAILURES=0
DUPLICATE_BUSINESS_SIDE_EFFECTS=0
ACCEPTED_EVENT_LOSS=0
CHECKPOINT_REGRESSION=0
```

---

# 8. Phase 4 — Downstream Odoo and n8n Validation

Validate the intended downstream result before persistent operation.

## Odoo canary

Authorize a very small number of new finalized production calls to create or update only the approved normalized Odoo call records.

Requirements:

- exact business-unit and campaign mapping;
- canonical schema validation;
- durable idempotency;
- same event creates one logical Odoo result;
- duplicate delivery does not create another result;
- no unrelated lead, customer, opportunity, appointment, campaign, agent, or telephony write;
- complete audit;
- reconciliation to Server B source;
- reversible or compensatable test result where possible.

## n8n canary

Authorize only the specifically accepted production canary workflow.

Requirements:

- workflow code and version recorded;
- production credential reference approved;
- idempotency enforced before external nodes;
- no customer-facing communication in the initial canary;
- no callback or telephony action;
- result returned through middleware;
- duplicate input causes no repeated action;
- permanent failure enters a reviewed dead-letter path;
- workflow remains inactive outside the bounded canary window.

Required result:

```text
ODOO_CANARY=PASS
ODOO_DUPLICATE_SIDE_EFFECTS=0
ODOO_UNRELATED_WRITES=0
N8N_CANARY=PASS
N8N_DUPLICATE_SIDE_EFFECTS=0
N8N_EXTERNAL_CUSTOMER_MESSAGES=0
DOWNSTREAM_RECONCILIATION=PASS
```

---

# 9. Phase 5 — Monitoring and Alerting

Production activation requires complete operational monitoring.

Monitor and alert on:

- service stopped;
- restart loop;
- last successful source read;
- last successful accepted delivery;
- last checkpoint advance;
- pending queue depth;
- retrying queue depth;
- failed or dead-letter depth;
- oldest pending age;
- oldest retry age;
- 401 and 403 rate;
- 409 conflict rate;
- 429 rate;
- timeout rate;
- TLS failure rate;
- 5xx rate;
- schema rejection;
- idempotency rejection;
- source-to-checkpoint lag;
- outbox lag;
- Odoo delivery lag;
- n8n execution lag;
- reconciliation mismatch;
- disk capacity;
- inode capacity;
- MariaDB connection health;
- PostgreSQL connection health;
- worker CPU and memory;
- HMAC or certificate expiration;
- feature-flag state;
- kill-switch state.

Requirements:

- dashboards;
- actionable alerts;
- named owner;
- severity;
- escalation path;
- runbook link;
- alert test;
- alert recovery test;
- no secrets or high-cardinality customer identifiers in metrics.

Required result:

```text
PRODUCTION_MONITORING=PASS
CRITICAL_ALERTS_TESTED=PASS
ALERT_RECOVERY_TESTED=PASS
MONITORING_OWNER=RECORDED
```

---

# 10. Phase 6 — Consolidated Cutover and Rollback Runbook

Create one authoritative runbook recording:

- change ID;
- operator;
- approver;
- maintenance or quiet window;
- starting source watermark;
- legacy quarantine reference;
- event budget;
- allowed event types;
- allowed downstream effects;
- service and feature-flag sequence;
- validation queries;
- success thresholds;
- abort thresholds;
- emergency-stop procedure;
- rollback operator;
- rollback commands or maintained procedure;
- rollback validation;
- evidence directory;
- communication and escalation plan.

The rollback rehearsal must prove:

- service can be stopped;
- `SEND_EVENTS` can return to false;
- service can return to disabled/inactive;
- source checkpoint is preserved;
- accepted events are not silently lost;
- uncertain events are quarantined;
- Odoo duplicate protection remains intact;
- n8n workflow can be deactivated;
- no telephony state changes;
- queues and legacy quarantine remain preserved.

Required result:

```text
CUTOVER_RUNBOOK=PASS
ROLLBACK_REHEARSAL=PASS
EMERGENCY_STOP=PASS
ROLLBACK_OPERATOR=RECORDED
```

---

# 11. Phase 7 — Bounded New-Events-Only Production Soak

The first live soak is authorized only after Phases 1 through 6 pass.

## Event budget

Use between 5 and 10 newly finalized production calls.

Use no historical records.

Initial event type:

- `call_ended` only.

Required scenario coverage when naturally available within the approved window:

- outbound answered;
- outbound non-answered;
- inbound answered;
- inbound non-answered;
- at least two records sharing a timestamp or an equivalent deterministic-order fixture;
- restart and checkpoint continuity.

Do not originate calls solely for the soak unless a separate telephony test-call authorization exists.

## Downstream scope

Permit:

- middleware ingestion;
- PostgreSQL idempotency and audit;
- accepted Odoo call result;
- the accepted bounded n8n canary workflow without customer communication.

Do not permit:

- callbacks;
- telephony control;
- customer email;
- customer SMS;
- social messages;
- AI voice;
- unrelated Odoo workflows.

## Acceptance

Require:

- selected records equal the approved new-event budget;
- historical records selected: zero;
- accepted events missing: zero;
- duplicate canonical events: zero;
- duplicate Odoo results: zero;
- duplicate n8n actions: zero;
- schema failures: zero;
- sensitive-field violations: zero;
- checkpoint errors: zero;
- unintended actions: zero;
- reconciliation gaps: zero;
- bounded retries;
- no retry storm;
- rollback remains available.

Required result:

```text
BOUNDED_LIVE_SOAK=PASS
NEW_EVENTS_PROCESSED=<5_to_10>
HISTORICAL_EVENTS_PROCESSED=0
MISSING_EVENTS=0
DUPLICATE_EVENTS=0
UNINTENDED_ACTIONS=0
RECONCILIATION_GAPS=0
```

Rollback immediately on any failure.

---

# 12. Phase 8 — Progressive Production Soaks

Proceed only after the bounded soak passes.

## Stage A — One-hour monitored soak

Requirements:

- `call_ended` only;
- new finalized rows only;
- event budget and rate limit;
- continuous monitoring;
- downstream Odoo and accepted n8n processing;
- no customer communication;
- final reconciliation.

## Stage B — One-business-day monitored soak

Requirements:

- same event scope;
- no historical records;
- stable checkpoint;
- no restart loop;
- accepted latency;
- zero unexplained mismatch;
- alerts tested;
- operator coverage;
- rollback ready.

## Stage C — Persistent operation

Only after Stage B passes:

- enable the production worker at boot;
- set the accepted persistent event-delivery flag true;
- retain the kill switch;
- retain legacy hard watermark;
- retain batch, backlog, and retry bounds;
- retain monitoring;
- retain daily reconciliation.

Do not expand event types during the same change.

Required result:

```text
ONE_HOUR_SOAK=PASS
ONE_BUSINESS_DAY_SOAK=PASS
BOOT_PERSISTENCE=PASS
PERSISTENT_SEND_EVENTS=true
KILL_SWITCH=AVAILABLE
```

---

# 13. Phase 9 — Controlled Event-Type Expansion

After stable `call_ended` production operation, expand one event family at a time.

For each additional event type:

1. Contract and schema accepted.
2. Source boundary accepted.
3. Privacy field allowlist accepted.
4. Worker regression passed.
5. Downstream side effects accepted.
6. Monitoring added.
7. Bounded canary passed.
8. One-hour soak passed.
9. Reconciliation passed.
10. Rollback passed.

Do not enable all event types simultaneously.

Agent-status events require an independent volume, privacy, deduplication, and downstream-capacity review before activation.

The 980 legacy `agent_status` rows remain quarantined permanently unless a separate replay authorization is issued.

---

# 14. Immediate Abort and Rollback Triggers

Rollback immediately for:

- any historical event selected;
- any source write;
- any duplicate business side effect;
- any missing accepted event;
- any unexplained reconciliation gap;
- checkpoint regression;
- checkpoint corruption;
- sensitive field leakage;
- unexpected Odoo write;
- unexpected n8n execution;
- callback or telephony action;
- customer communication during restricted stages;
- repeated 401 or 403;
- unresolved TLS failure;
- uncontrolled 429 or 5xx retry storm;
- backlog beyond the approved limit;
- oldest pending age beyond the approved limit;
- worker restart loop;
- monitoring blindness;
- disk or database capacity risk;
- kill switch failure;
- rollback verification failure;
- production flag outside approved sequence.

Rollback procedure:

1. Activate the kill switch.
2. Stop the production worker.
3. Set event delivery false.
4. Disable persistent service operation.
5. Preserve checkpoint, queue, logs, and evidence.
6. Quarantine uncertain in-flight events.
7. Disable the n8n production canary workflow.
8. Verify no telephony change.
9. Reconcile accepted downstream results.
10. Restore the previous verified service/configuration state.
11. Verify monitoring and service health.
12. Release locks normally.
13. Report the exact trigger and state.

---

# 15. Final Production Acceptance Requirements

Persistent `call_ended` production operation may be accepted only when:

```text
SPECIFICATIONS_AUTHENTICATED=PASS
LOCKS=PASS
LEGACY_QUEUE_QUARANTINE=PASS
LIVE_SOURCE_BOUNDARY=PASS
PRODUCTION_WORKER_REGRESSION=PASS
ODOO_CANARY=PASS
N8N_CANARY=PASS
MONITORING=PASS
CUTOVER_RUNBOOK=PASS
ROLLBACK_REHEARSAL=PASS
BOUNDED_LIVE_SOAK=PASS
ONE_HOUR_SOAK=PASS
ONE_BUSINESS_DAY_SOAK=PASS
RECONCILIATION=PASS
SECURITY=PASS

HISTORICAL_EVENTS_PROCESSED=0
DUPLICATE_BUSINESS_SIDE_EFFECTS=0
ACCEPTED_EVENT_LOSS=0
SENSITIVE_FIELD_VIOLATIONS=0
UNEXPLAINED_RECONCILIATION_GAPS=0
UNINTENDED_TELEPHONY_ACTIONS=0
EXTERNAL_CUSTOMER_MESSAGES_DURING_RESTRICTED_STAGES=0
```

Then and only then:

```text
CALL_ENDED_PRODUCTION_OPERATION=ACTIVE
WORKER_BOOT_PERSISTENCE=ENABLED
PERSISTENT_SEND_EVENTS=true
PRODUCTION_READY_FOR_CALL_ENDED=YES
FULL_PLATFORM_PRODUCTION_READY=NO
```

The full platform remains not ready until every additional event type, n8n workflow, communication channel, AI feature, callback path, provisioning path, and telephony-control path passes its own production gate.

---

# 16. Required Final Report

Return:

```text
CHANGE_ID=
OVERALL_STATUS=

LEGACY_QUEUE_TOTAL=
LEGACY_QUEUE_QUARANTINED=
LEGACY_QUEUE_PRODUCTION_ELIGIBLE=
HARD_STARTING_WATERMARK=

SOURCE_BOUNDARY_PROOF=
FINALIZED_PREDICATES=
DETERMINISTIC_ORDERING=
HISTORICAL_ROWS_SELECTED=

PRODUCTION_WORKER_REGRESSION=
TOTAL_TESTS=
TEST_FAILURES=
ACCEPTED_EVENT_LOSS=
DUPLICATE_BUSINESS_SIDE_EFFECTS=

ODOO_CANARY=
N8N_CANARY=
EXTERNAL_CUSTOMER_MESSAGES=
DOWNSTREAM_RECONCILIATION=

PRODUCTION_MONITORING=
CRITICAL_ALERTS_TESTED=
CUTOVER_RUNBOOK=
ROLLBACK_REHEARSAL=

BOUNDED_LIVE_SOAK=
BOUNDED_EVENT_COUNT=
ONE_HOUR_SOAK=
ONE_BUSINESS_DAY_SOAK=

WORKER_BOOT_PERSISTENCE=
PERSISTENT_SEND_EVENTS=
KILL_SWITCH=

PRODUCTION_FLAGS_TRUE=
HISTORICAL_EVENTS_PROCESSED=
UNINTENDED_TELEPHONY_ACTIONS=
UNEXPLAINED_RECONCILIATION_GAPS=

CALL_ENDED_PRODUCTION_OPERATION=
PRODUCTION_READY_FOR_CALL_ENDED=
FULL_PLATFORM_PRODUCTION_READY=

EVIDENCE_DIRECTORY=
LEGACY_QUARANTINE_MANIFEST=
SOURCE_BOUNDARY_REPORT=
REGRESSION_REPORT=
MONITORING_REPORT=
CUTOVER_RUNBOOK_PATH=
ROLLBACK_REPORT=
SOAK_REPORT=
RECONCILIATION_REPORT=
FINAL_REPORT=
FINAL_REPORT_SHA256=
```

---

# 17. Paste-Ready Codex Mandate

Proceed autonomously with full root engineering access to complete the production-readiness and staged cutover program in this document.

Do not immediately enable every component.

Treat the current disabled state as the protected baseline.

Authenticate the specifications, acquire the project locks, capture the baseline, and preserve rollback assets first.

Indefinitely quarantine all 1,110 legacy events. Do not delete, replay, mark sent, or make them production eligible.

Prove the live finalized-source boundary directly against read-only production data.

Complete regression testing of the actual production worker.

Validate the intended Odoo and n8n downstream result with duplicate protection and no customer communication.

Implement and test production monitoring and alerts.

Create and rehearse the consolidated cutover and rollback runbook.

Then run the staged sequence:

1. Five-to-ten new finalized `call_ended` events.
2. One-hour monitored soak.
3. One-business-day monitored soak.
4. Persistent boot operation for `call_ended` only.

Do not process historical records.

Do not enable all event types together.

Do not activate customer communications, callbacks, AI voice, telephony control, predictive dialing, carriers, DIDs, or unrelated campaigns.

Correct defects autonomously and rerun every affected test.

Rollback immediately on any historical selection, duplicate side effect, missing event, sensitive-field leak, checkpoint error, unintended action, retry storm, reconciliation gap, monitoring failure, or kill-switch failure.

Claim production acceptance only for `call_ended` after every mandatory gate passes.

Finish with the complete evidence-backed final report.
