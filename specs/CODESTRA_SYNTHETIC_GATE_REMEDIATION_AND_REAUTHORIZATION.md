# Codestra Synthetic Gate Remediation and Reauthorization for Codex

## Purpose

Remediate the failed synthetic-call preconditions, rotate the exposed VICIdial database credential, establish fully isolated synthetic telephony fixtures, issue a fresh bounded destination approval, and rerun the synthetic call gate.

This document supplements:

- `CODESTRA_PRODUCTION_READINESS_AND_STAGED_CUTOVER_AUTHORIZATION.md`
- `CODESTRA_SYNTHETIC_CALL_GATE_AUTHORIZATION.md`

It does not authorize unrestricted production activation.

---

# 1. Authorization

```text
CHANGE_ID=CHG-20260725-SYNTHETIC-GATE-REMEDIATION-01
APPROVER=Ralph L. Appolon
APPROVAL_DATE=2026-07-25

ROOT_ENGINEERING_AUTHORIZED=YES
AUTONOMOUS_REMEDIATION_AUTHORIZED=YES
CREDENTIAL_ROTATION_AUTHORIZED=YES
SYNTHETIC_AGENT_PROVISIONING_AUTHORIZED=YES
SYNTHETIC_CAMPAIGN_PROVISIONING_AUTHORIZED=YES
SYNTHETIC_DID_QUEUE_PROVISIONING_AUTHORIZED=YES
SYNTHETIC_ENDPOINT_PROVISIONING_AUTHORIZED=YES
BOUNDED_SYNTHETIC_CALL_TEST_AUTHORIZED=YES
MAX_SYNTHETIC_CALLS=10
CUSTOMER_DESTINATIONS_AUTHORIZED=NO
PRODUCTION_CAMPAIGNS_AUTHORIZED=NO
PREDICTIVE_DIALING_AUTHORIZED=NO
PUBLIC_DID_CHANGES_AUTHORIZED=NO
CARRIER_CONFIGURATION_CHANGES_AUTHORIZED=NO
HISTORICAL_REPLAY_AUTHORIZED=NO
CUSTOMER_COMMUNICATION_AUTHORIZED=NO
FULL_PRODUCTION_ACTIVATION_AUTHORIZED=NO
```

---

# 2. Current Baseline

Treat the following as the required protected baseline:

```text
LEGACY_QUEUE_QUARANTINED=1110
LEGACY_QUEUE_PRODUCTION_ELIGIBLE=0
PRODUCTION_PENDING=0
PRODUCTION_EVENT_ROWS=0
ACTIVE_CALLS=0
ACTIVE_CHANNELS=0
SYNC_ENABLED=disabled
SYNC_ACTIVE=inactive
SEND_EVENTS=false
KILL_SWITCH=active
```

Before remediation, identify and classify the one non-quarantined queue row represented by:

```text
QUEUE_TOTAL=1111
QUARANTINED=1110
```

It must be proven to be an accepted synthetic or terminal record and not pending, retrying, historical, or production-eligible.

---

# 3. Mandatory Credential-Incident Response

A VICIdial database credential appeared in diagnostic output.

Treat the credential as compromised.

Codex must:

1. Identify the exact credential and every authorized consumer without printing the value.
2. Identify where it was exposed:
   - terminal transcript;
   - evidence;
   - logs;
   - shell history;
   - process output;
   - temporary files;
   - monitoring or debugging output.
3. Preserve the original incident evidence under restricted root-only access.
4. Create a sanitized incident report containing only:
   - credential identifier;
   - affected service names;
   - exposure timestamp;
   - exposure channel;
   - rotation status;
   - revocation status;
   - validation status.
5. Generate a new strong credential using a protected mechanism.
6. Update every authorized consumer atomically or through a controlled compatibility window.
7. Revoke the old credential.
8. Verify the old credential fails.
9. Verify every authorized consumer works with the new credential.
10. Verify no unauthorized source can authenticate.
11. Restart or reload only the minimum affected non-telephony service when necessary.
12. Do not restart Asterisk, VICIdial, MariaDB, or Apache unless a separately approved emergency requirement exists.
13. Scan:
    - repository;
    - service configurations;
    - environment templates;
    - logs;
    - evidence;
    - shell history;
    - temporary files;
    - systemd unit and drop-ins.
14. Redact or restrict derivative copies while preserving auditable incident evidence.
15. Rotate any signing, retrieval, or dependent secret only when the exposure analysis proves it was also revealed.

Required result:

```text
EXPOSED_CREDENTIAL_IDENTIFIED=YES
EXPOSED_CREDENTIAL_VALUE_REPRINTED=NO
NEW_CREDENTIAL_GENERATED=YES
AUTHORIZED_CONSUMERS_UPDATED=PASS
OLD_CREDENTIAL_REVOKED=PASS
OLD_CREDENTIAL_REJECTED=PASS
NEW_CREDENTIAL_ACCEPTED=PASS
UNAUTHORIZED_ACCESS_REJECTED=PASS
SECRET_SCAN=PASS
DIAGNOSTIC_OUTPUT_SANITIZED=PASS
```

Do not continue to fixture creation until credential rotation and validation pass.

---

# 4. Diagnostic Output Hardening

Correct the diagnostic process that revealed the credential.

Requirements:

- never print complete environment files;
- never print database connection strings;
- never print protected defaults files;
- never print secrets through exception objects;
- never print process command lines containing credentials;
- use field allowlists for diagnostic output;
- mask all secret-bearing fields;
- validate redaction with positive and negative fixtures;
- fail closed when redaction cannot be guaranteed;
- prohibit unrestricted `env`, `set`, `export`, `ps aux`, and configuration dumps in evidence collection;
- add tests proving protected values do not appear in stdout, stderr, logs, evidence, or reports.

Required result:

```text
DIAGNOSTIC_REDACTION_TESTS=PASS
PROTECTED_VALUES_IN_STDOUT=0
PROTECTED_VALUES_IN_STDERR=0
PROTECTED_VALUES_IN_LOGS=0
PROTECTED_VALUES_IN_EVIDENCE=0
```

---

# 5. Isolated Synthetic Telephony Fixtures

Create or reconcile dedicated test-only fixtures.

## Required fixtures

- one synthetic user group;
- at least two synthetic agents;
- one outbound synthetic campaign;
- one inbound synthetic campaign;
- one numeric synthetic list where VICIdial requires it;
- one synthetic inbound group or queue;
- one test-only DID or internal DID mapping;
- at least two registered test endpoints;
- one internal or isolated test destination;
- one synthetic recording location when recording-reference testing is required.

## Fixture requirements

Every fixture must be:

- clearly marked test-only;
- production-ineligible;
- inactive outside the gate;
- excluded from predictive dialing;
- excluded from production lead sources;
- excluded from unrestricted carriers;
- excluded from customer routes;
- bounded by expiration;
- associated with the change ID;
- associated with a rollback reference;
- protected by a dedicated namespace;
- included in the reconciliation manifest;
- disabled or revoked after the test.

Use the existing accepted VICIdial identifier limits.

Do not modify production users, campaigns, lists, phones, DIDs, queues, trunks, or endpoints.

---

# 6. Registered Test Endpoints

The prior gate failed because prepared identities were not registered and no isolated Asterisk endpoint was available.

Codex must:

1. Create or reconcile test-only endpoint configuration through the accepted provisioning path.
2. Use one endpoint for the synthetic agent side.
3. Use another endpoint, echo service, or isolated SIPp fixture for the destination side.
4. Prevent registration from public or unapproved networks.
5. Use short-lived credentials.
6. Avoid placing credentials in Odoo, Git, reports, command lines, or evidence.
7. Validate:
   - registration;
   - authentication failure;
   - expiration;
   - revocation;
   - no public exposure;
   - no production route access.
8. Revoke and unregister all test endpoints after the gate.

Required result:

```text
SYNTHETIC_ENDPOINTS_REGISTERED=PASS
PUBLIC_ENDPOINT_EXPOSURE=NONE
PRODUCTION_ROUTE_ACCESS=DENIED
ENDPOINT_REVOCATION_TEST=PASS
```

---

# 7. Fresh Bounded Destination Approval

Issue one current approval for an internal or isolated non-customer destination.

The approval must record:

- destination identifier;
- destination type;
- allowed source agent or endpoint;
- allowed campaign;
- allowed direction;
- maximum calls;
- maximum duration;
- start time;
- expiration time;
- allowed business unit;
- expected cost, which must be zero or explicitly accepted;
- recording policy;
- owner;
- rollback method.

Requirements:

- no customer number;
- no public customer-facing DID;
- no emergency or premium destination;
- no unrestricted carrier route;
- automatic expiration;
- no reuse after expiration;
- test only;
- maximum ten calls.

Required result:

```text
DESTINATION_APPROVAL=PASS
DESTINATION_CUSTOMER_OWNED=NO
DESTINATION_PUBLIC_ROUTE=NO
DESTINATION_APPROVAL_EXPIRED=NO
MAX_CALLS=10
```

---

# 8. Explicit Temporary Gate Flags

The previous gate remained blocked because required flags were false.

Authorize only these temporary synthetic-gate values:

```text
LIVE_CALL_TEST_ALLOWED=true
VICIDIAL_WRITE_ALLOWED=true_SYNTHETIC_NAMESPACE_ONLY
AGENT_PROVISIONING_ALLOWED=true_SYNTHETIC_NAMESPACE_ONLY
CAMPAIGN_PROVISIONING_ALLOWED=true_SYNTHETIC_NAMESPACE_ONLY
ENDPOINT_PROVISIONING_ALLOWED=true_SYNTHETIC_NAMESPACE_ONLY
SYNTHETIC_CALL_GATE_ACTIVE=true
```

All other production flags remain false.

Restrictions:

- flags are scoped to the change ID;
- flags are scoped to test namespaces;
- flags have an expiration;
- flags are checked by middleware and adapters;
- flags cannot authorize production objects;
- flags cannot authorize customer destinations;
- flags cannot authorize predictive dialing;
- flags cannot authorize carrier or DID changes;
- flags return to false immediately after testing or rollback.

Required final values:

```text
LIVE_CALL_TEST_ALLOWED=false
VICIDIAL_WRITE_ALLOWED=false
AGENT_PROVISIONING_ALLOWED=false
CAMPAIGN_PROVISIONING_ALLOWED=false
ENDPOINT_PROVISIONING_ALLOWED=false
SYNTHETIC_CALL_GATE_ACTIVE=false
```

---

# 9. Fresh Checkpoint and Rollback

Before fixture activation:

- capture Server A and Server B service state;
- capture feature flags;
- capture production aggregates;
- capture Asterisk configuration hashes;
- capture relevant VICIdial aggregate counts;
- capture current registrations;
- capture queues and active calls;
- back up changed test configuration;
- back up control-plane state;
- generate SHA-256 manifests;
- verify restore in an isolated environment;
- record rollback operator and procedure.

Do not proceed when restore verification fails.

---

# 10. Rerun the Synthetic Call Gate

After all remediation gates pass, execute:

`CODESTRA_SYNTHETIC_CALL_GATE_AUTHORIZATION.md`

Required scenario coverage:

- outbound answered;
- outbound non-answered;
- inbound answered;
- inbound non-answered;
- deterministic ordering;
- restart/checkpoint continuity;
- Odoo idempotency;
- n8n idempotency;
- monitoring;
- reconciliation;
- rollback.

Maximum calls: ten.

Minimum calls: five.

No customer calls.

No historical events.

No boot persistence.

No customer communication.

No callbacks.

No AI voice.

No additional event families.

---

# 11. Cleanup

After PASS or rollback:

- stop the bounded worker;
- set `SEND_EVENTS=false`;
- keep the persistent worker disabled;
- activate the kill switch;
- set all temporary gate flags false;
- deactivate synthetic campaigns;
- disable synthetic agents;
- detach synthetic DIDs;
- empty or deactivate synthetic queues;
- revoke test credentials;
- unregister test endpoints;
- invalidate unused retrieval tokens;
- preserve synthetic event and audit evidence;
- reconcile fixture state;
- verify production aggregates unchanged;
- verify historical quarantine unchanged.

---

# 12. Immediate Abort Triggers

Abort for:

- credential exposure;
- old credential still authenticates;
- unauthorized consumer authentication;
- customer destination selected;
- production object mutation;
- historical event selection;
- event at or before the hard watermark;
- predictive dialing;
- public route use;
- carrier or DID mutation;
- duplicate effect;
- missing event;
- sensitive-field leak;
- checkpoint regression;
- monitoring gap;
- rollback failure;
- any action outside the synthetic namespace.

---

# 13. Required Final Report

Return:

```text
CHANGE_ID=CHG-20260725-SYNTHETIC-GATE-REMEDIATION-01
OVERALL_STATUS=

CREDENTIAL_INCIDENT=CONFIRMED
EXPOSED_CREDENTIAL_ROTATED=
OLD_CREDENTIAL_REVOKED=
OLD_CREDENTIAL_REJECTED=
AUTHORIZED_CONSUMERS_UPDATED=
SECRET_SCAN=
DIAGNOSTIC_REDACTION_TESTS=

QUEUE_TOTAL=
QUARANTINED=
NON_QUARANTINED_ROW_CLASSIFICATION=
LEGACY_QUEUE_PRODUCTION_ELIGIBLE=

SYNTHETIC_USER_GROUP=
SYNTHETIC_AGENTS=
SYNTHETIC_OUTBOUND_CAMPAIGN=
SYNTHETIC_INBOUND_CAMPAIGN=
SYNTHETIC_LIST=
SYNTHETIC_QUEUE=
SYNTHETIC_DID=
SYNTHETIC_ENDPOINTS=
SYNTHETIC_ENDPOINTS_REGISTERED=

DESTINATION_APPROVAL=
DESTINATION_EXPIRATION=
DESTINATION_PUBLIC_ROUTE=
MAX_CALLS=

TEMPORARY_GATE_FLAGS_ENABLED=
TEMPORARY_GATE_FLAGS_FINAL_FALSE=

CHECKPOINT=
RESTORE_TEST=
ROLLBACK_PROCEDURE=

SYNTHETIC_GATE_RERUN=
SYNTHETIC_CALLS_PLACED=
CUSTOMER_CALLS_PLACED=
HISTORICAL_EVENTS_PROCESSED=
MISSING_EVENTS=
DUPLICATE_CANONICAL_EVENTS=
DUPLICATE_ODOO_RESULTS=
DUPLICATE_N8N_RESULTS=
SENSITIVE_FIELD_VIOLATIONS=
UNINTENDED_ACTIONS=
RECONCILIATION_GAPS=

WORKER_BOOT_PERSISTENCE=
SEND_EVENTS_FINAL=
KILL_SWITCH_FINAL=

FIXTURES_DISABLED=
ENDPOINTS_REVOKED=
PRODUCTION_AGGREGATES_UNCHANGED=
LEGACY_QUARANTINE_UNCHANGED=

EVIDENCE_DIRECTORY=
CREDENTIAL_INCIDENT_REPORT=
FIXTURE_MANIFEST=
DESTINATION_APPROVAL_RECORD=
CALL_MATRIX_REPORT=
RECONCILIATION_REPORT=
ROLLBACK_REPORT=
FINAL_REPORT=
FINAL_REPORT_SHA256=
```

Successful outcome:

```text
OVERALL_STATUS=SYNTHETIC_GATE_REMEDIATION_AND_RERUN_PASS
EXPOSED_CREDENTIAL_ROTATED=PASS
OLD_CREDENTIAL_REVOKED=PASS
OLD_CREDENTIAL_REJECTED=PASS
AUTHORIZED_CONSUMERS_UPDATED=PASS
SECRET_SCAN=PASS
DIAGNOSTIC_REDACTION_TESTS=PASS

LEGACY_QUEUE_PRODUCTION_ELIGIBLE=0
SYNTHETIC_ENDPOINTS_REGISTERED=PASS
DESTINATION_APPROVAL=PASS
TEMPORARY_GATE_FLAGS_FINAL_FALSE=PASS

SYNTHETIC_GATE_RERUN=PASS
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
FIXTURES_DISABLED=PASS
ENDPOINTS_REVOKED=PASS
PRODUCTION_AGGREGATES_UNCHANGED=PASS
LEGACY_QUARANTINE_UNCHANGED=PASS
```

---

# 14. Paste-Ready Codex Mandate

Proceed autonomously with full root engineering access to remediate and rerun the synthetic call gate.

Treat the exposed VICIdial database credential as compromised.

Rotate it without printing it, update every authorized consumer, revoke the old credential, prove old-credential rejection, and prove new-credential acceptance.

Correct the diagnostic process and pass redaction tests before continuing.

Create fully isolated synthetic agents, campaigns, list, DID, queue, and registered endpoints using test-only namespaces and non-customer routing.

Issue a fresh bounded destination approval for no more than ten calls.

Temporarily enable only the explicit synthetic-gate flags and scope them to the change ID, test namespace, and expiration.

Keep all production flags false.

Keep all 1,110 legacy records quarantined and production-ineligible.

Classify the one additional queue row and prove it is not pending, retrying, historical, or production-eligible.

Create a fresh checkpoint and verify rollback.

Then rerun the authenticated synthetic call gate.

Abort immediately for any credential leak, customer destination, production mutation, historical selection, duplicate effect, missing event, checkpoint regression, monitoring failure, or action outside the synthetic namespace.

Correct defects autonomously and rerun affected tests.

Finish fail-closed with all temporary flags false, `SEND_EVENTS=false`, boot persistence disabled, the kill switch active, all fixtures disabled, and all synthetic endpoints revoked.

Return the complete evidence-backed final report.
