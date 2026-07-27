# Codestra VoIP-to-Odoo Bounded Test Authorization

## Change Identification

```text
CHANGE_ID=CHG-20260725-VOIP-ODOO-ACCEPTANCE-01
APPROVER=Ralph L. Appolon
APPROVAL_DATE=2026-07-25
ROOT_ENGINEERING_AUTHORIZED=YES
BOUNDED_LIVE_TESTING_AUTHORIZED=YES
FULL_PRODUCTION_ACTIVATION_AUTHORIZED=NO
```

## Servers

```text
SERVER_A_PUBLIC=65.109.65.169
SERVER_A_PRIVATE=10.40.0.1
SERVER_A_ROLE=ODOO_MIDDLEWARE_N8N_AI_REPORTING

SERVER_B_PUBLIC=65.21.67.207
SERVER_B_PRIVATE=10.40.0.2
SERVER_B_ROLE=VICIDIAL_ASTERISK_TELEPHONY
```

## Purpose

This document authorizes a bounded VoIP-to-Odoo acceptance test using controlled test identities, campaigns, queues, endpoints, and non-customer destinations.

It does not authorize unrestricted production routing, predictive dialing, customer calling, carrier changes, public DID changes, or full production activation.

---

# 1. Approved Test Scope

## 1.1 Originating DID

The originating DID must be entered before execution in a protected test-target record.

Requirements:

- controlled by Codestra or the test operator;
- confirmed not to be assigned to a customer campaign;
- not an emergency, premium-rate, shared customer, or unrestricted public route;
- caller-ID presentation verified before the first external call;
- recorded in evidence by masked value and SHA-256 only.

```text
APPROVED_ORIGINATING_TEST_DID=REQUIRED_BEFORE_EXTERNAL_TEST
```

Internal-only tests may proceed without a public DID.

## 1.2 Destination Test Numbers

Only explicitly approved non-customer numbers may be called.

Each destination must be:

- owned or controlled by a named test participant;
- confirmed before testing;
- entered into a protected allowlist;
- automatically expired after the test window;
- blocked from reuse outside this change.

```text
APPROVED_DESTINATION_TEST_NUMBERS=REQUIRED_BEFORE_EXTERNAL_TEST
CUSTOMER_NUMBERS_ALLOWED=NO
EMERGENCY_NUMBERS_ALLOWED=NO
PREMIUM_RATE_NUMBERS_ALLOWED=NO
UNAPPROVED_INTERNATIONAL_NUMBERS_ALLOWED=NO
```

Internal extensions and isolated SIPp endpoints are approved when they cannot reach customer routes.

## 1.3 Test Users

Codex is authorized to create or reconcile the following test-only roles when equivalent synthetic accounts do not already exist:

- two test agents;
- one test supervisor;
- one test closer where transfer validation requires it.

Requirements:

- synthetic namespace;
- no access to customer campaigns;
- no unrestricted export rights;
- no production lead ownership;
- short-lived credentials;
- mandatory cleanup and revocation.

```text
TEST_AGENT_ACCOUNTS=2_MAXIMUM
TEST_SUPERVISOR_ACCOUNTS=1_MAXIMUM
TEST_CLOSER_ACCOUNTS=1_MAXIMUM
```

## 1.4 Approved Test Campaigns

The following test-only campaign families are approved:

```text
TL-TEST-OUT
TL-TEST-IN
DEV-TEST-OUT
DEV-TEST-IN
SCP-TEST-OUT
SCP-TEST-IN
```

Requirements:

- inactive before and after the test;
- manual or controlled dialing only;
- predictive dialing disabled;
- no production lists;
- no customer leads;
- no unrestricted carrier route;
- hard test-only eligibility metadata;
- complete rollback reference.

## 1.5 Approved Inbound Test Queues

Codex may create or reconcile one test-only inbound queue per business unit:

```text
TL-TEST-IN
DEV-TEST-IN
SCP-TEST-IN
```

The queues must not be attached to public customer DIDs outside the bounded test window.

## 1.6 After-Hours Test Window

Authorize one quiet window of no more than 60 minutes.

The operator must record before execution:

- timezone;
- start time;
- end time;
- active-call count;
- queued-call count;
- on-call operator;
- rollback operator.

```text
TEST_WINDOW_DURATION_MAX=60_MINUTES
ACTIVE_PRODUCTION_CALLS_REQUIRED=0
QUEUED_PRODUCTION_CALLS_REQUIRED=0
```

If the system is not quiet, stop without testing.

## 1.7 External Transfer

An external transfer is authorized only to one explicitly approved controlled destination already present in the protected destination allowlist.

```text
EXTERNAL_TRANSFER_DESTINATION=REQUIRED_BEFORE_EXTERNAL_TRANSFER_TEST
UNAPPROVED_TRANSFER_DESTINATIONS_ALLOWED=NO
```

Internal agent-to-agent and queue-to-agent transfers may proceed inside the synthetic namespace.

## 1.8 Recording Consent

Recording is authorized only when:

- all participants are test participants;
- each participant is informed before the call;
- each participant affirmatively consents;
- consent is recorded in the test evidence;
- no customer audio is captured.

```text
RECORDING_CONSENT_REQUIRED=YES
CUSTOMER_RECORDINGS_ALLOWED=NO
```

## 1.9 Controlled Audio Endpoints

At least two controlled people or endpoints must be available.

They must verify:

- audio from caller to agent;
- audio from agent to caller;
- hold music where applicable;
- transfer audio;
- no one-way audio;
- no unexpected recording or playback.

```text
CONTROLLED_AUDIO_ENDPOINTS_REQUIRED=2
```

---

# 2. Approved Limits

```text
MAXIMUM_TEST_CALLS=10
MAXIMUM_TOTAL_CARRIER_CHARGES_USD=5.00
MAXIMUM_SINGLE_CALL_DURATION_MINUTES=10
MAXIMUM_TEST_WINDOW_MINUTES=60
MAXIMUM_EXTERNAL_TRANSFER_TESTS=2
MAXIMUM_CALLBACK_TESTS=3
MAXIMUM_TEST_RECORDINGS=10
```

Stop automatically when any limit is reached.

Do not raise these limits without a new authorization.

---

# 3. Authorized Actions

Codex is authorized to:

- create synthetic test users and roles;
- create inactive test campaigns;
- create test queues and internal DIDs;
- register isolated test endpoints;
- create a protected destination allowlist;
- place up to ten bounded test calls;
- answer bounded inbound test calls;
- verify two-way audio;
- validate caller ID;
- validate queue routing;
- perform internal transfers;
- perform up to two transfers to one approved controlled external destination;
- create up to three synthetic callbacks;
- create and retain up to ten synthetic test recordings;
- create or update synthetic Odoo test records;
- validate middleware, event, Odoo, and n8n idempotency;
- rotate test credentials;
- rotate any credential proven exposed during testing;
- run monitoring, recovery, reconciliation, and rollback tests;
- correct defects autonomously;
- rerun affected tests within the same limits.

---

# 4. Odoo Authorization

Codex may create or update only records carrying explicit synthetic/test metadata.

Approved Odoo records may include:

- test contacts;
- test leads;
- test opportunities;
- test calls;
- test appointments;
- test callbacks;
- test recordings references;
- test audit records;
- test reporting snapshots;
- test reconciliation findings.

Requirements:

- test namespace;
- no real customer linkage;
- no real payment;
- no real quotation acceptance;
- no real fulfillment;
- no customer communication;
- cleanup or archival after testing;
- duplicate-event protection;
- full audit.

```text
ODOO_TEST_WRITES_AUTHORIZED=YES_SYNTHETIC_ONLY
ODOO_PRODUCTION_CUSTOMER_WRITES_AUTHORIZED=NO
```

---

# 5. Callback Authorization

Test callbacks are authorized only when:

- tied to a synthetic contact;
- tied to a test campaign;
- directed to an approved controlled endpoint;
- not sent to a customer;
- automatically expired;
- duplicate protected;
- disabled after the test.

```text
TEST_CALLBACKS_AUTHORIZED=YES
MAXIMUM_CALLBACKS=3
CUSTOMER_CALLBACKS_AUTHORIZED=NO
```

---

# 6. Recording Authorization and Retention

Synthetic test recording is authorized.

Requirements:

- informed consent;
- test participants only;
- encrypted or protected storage;
- no public URL;
- no raw filesystem path exposed to Odoo or n8n;
- opaque recording reference;
- access audit;
- maximum retention of seven days unless preserved as restricted acceptance evidence;
- secure deletion or evidence retention decision after the test.

```text
TEST_RECORDINGS_AUTHORIZED=YES
MAXIMUM_RECORDINGS=10
DEFAULT_RETENTION_DAYS=7
CUSTOMER_AUDIO_AUTHORIZED=NO
```

---

# 7. Credential Rotation Authorization

Codex may rotate:

- synthetic SIP credentials;
- synthetic VICIdial credentials;
- synthetic service credentials;
- temporary retrieval tokens;
- any credential directly exposed during this test.

Codex may not rotate unrelated production credentials without proof that they were exposed or are direct dependencies of the test.

Requirements:

- never print the new value;
- update every approved consumer;
- revoke the old value;
- prove old-value rejection;
- prove new-value acceptance;
- scan logs and evidence;
- record identifiers and status only.

```text
TEST_CREDENTIAL_ROTATION_AUTHORIZED=YES
UNRELATED_PRODUCTION_CREDENTIAL_ROTATION_AUTHORIZED=NO
```

---

# 8. Required Acceptance Matrix

## 8.1 Outbound

Test:

- answered call;
- no-answer call;
- busy or rejected call where supported;
- caller-ID presentation;
- disposition;
- recording reference;
- event delivery;
- Odoo synchronization;
- duplicate replay.

## 8.2 Inbound

Test:

- DID resolution;
- IVR or menu selection;
- language selection where configured;
- queue routing;
- answer;
- abandonment or no-answer;
- after-hours behavior;
- callback request;
- Odoo context;
- event delivery.

## 8.3 Audio

Verify:

- caller-to-agent audio;
- agent-to-caller audio;
- no one-way audio;
- acceptable latency;
- hold and resume;
- transfer audio;
- recording completion.

## 8.4 Transfers

Test:

- agent-to-agent;
- agent-to-closer;
- queue transfer;
- one approved external transfer;
- transfer failure recovery;
- cross-campaign rejection.

## 8.5 Odoo and Automation

Verify:

- one call creates one logical call record;
- duplicate event creates no duplicate record;
- correct campaign;
- correct business unit;
- correct agent;
- correct disposition;
- correct recording reference;
- n8n canary executes once;
- no customer communication;
- no unrelated Odoo writes.

## 8.6 Security

Verify:

- mTLS;
- service authentication;
- wrong identity rejection;
- wrong campaign rejection;
- wrong business-unit rejection;
- replay rejection;
- secret redaction;
- no public internal API;
- no credential in logs or evidence.

## 8.7 Monitoring and Recovery

Verify:

- health and readiness;
- call and channel state;
- queue state;
- endpoint state;
- event queue depth;
- checkpoint;
- retries;
- worker restart;
- reconnect;
- rollback;
- cleanup.

---

# 9. Hard Preconditions

Before the first call, Codex must prove:

```text
CANONICAL_AUTHORIZATION=PASS
PROJECT_LOCKS=PASS
ROLLBACK_CHECKPOINT=PASS
ASTERISK_HEALTH=PASS
VICIDIAL_HEALTH=PASS
MARIADB_HEALTH=PASS
ODOO_HEALTH=PASS
MIDDLEWARE_HEALTH=PASS

ACTIVE_PRODUCTION_CALLS=0
QUEUED_PRODUCTION_CALLS=0

TEST_DID_APPROVED=PASS_OR_INTERNAL_ONLY
TEST_DESTINATIONS_APPROVED=PASS
TEST_USERS_ISOLATED=PASS
TEST_CAMPAIGNS_INACTIVE=PASS
TEST_QUEUES_ISOLATED=PASS
TEST_ENDPOINTS_REGISTERED=PASS
RECORDING_CONSENT=PASS
AUDIO_ENDPOINTS_AVAILABLE=2
CARRIER_CHARGE_LIMIT=5.00_USD
CALL_LIMIT=10
```

No call may begin when any required value is unknown.

---

# 10. Immediate Abort Triggers

Abort and roll back for:

- customer number selected;
- emergency or premium number selected;
- unapproved destination;
- test cost exceeding the approved limit;
- call count exceeding ten;
- production campaign activation;
- predictive dialing activation;
- production lead selection;
- unexpected public DID routing;
- unauthorized external transfer;
- customer communication;
- one-way audio;
- dropped production call;
- sensitive data or credential exposure;
- historical event processing;
- duplicate business side effect;
- missing event;
- checkpoint regression;
- unexpected Odoo write;
- unexpected n8n workflow;
- monitoring failure;
- rollback failure.

---

# 11. Required Final State

After PASS or rollback:

```text
TEST_CAMPAIGNS_ACTIVE=NO
PREDICTIVE_DIALING_ACTIVE=NO
TEST_USERS_DISABLED_OR_RETAINED_INACTIVE=YES
TEST_ENDPOINTS_REVOKED_OR_DISABLED=YES
TEST_DIDS_DETACHED=YES
TEST_QUEUES_INACTIVE=YES
TEMPORARY_CREDENTIALS_REVOKED=YES

CUSTOMER_CALLS_PLACED=0
EMERGENCY_CALLS_PLACED=0
PREMIUM_CALLS_PLACED=0
UNAPPROVED_CALLS_PLACED=0
CUSTOMER_MESSAGES_SENT=0

PRODUCTION_ROUTING_CHANGED=NO
CARRIERS_CHANGED=NO
PUBLIC_DIDS_CHANGED=NO
PRODUCTION_READY=NO
```

Full production activation remains a separate approval.

---

# 12. Required Final Report

Return:

```text
CHANGE_ID=CHG-20260725-VOIP-ODOO-ACCEPTANCE-01
OVERALL_STATUS=

APPROVED_ORIGINATING_DID=
APPROVED_DESTINATIONS=
TEST_WINDOW=
TEST_AGENT_ACCOUNTS=
TEST_SUPERVISOR_ACCOUNT=
TEST_CAMPAIGNS=
TEST_QUEUES=
EXTERNAL_TRANSFER_DESTINATION=
RECORDING_CONSENT=
AUDIO_ENDPOINTS=

TEST_CALLS_PLACED=
OUTBOUND_ANSWERED=
OUTBOUND_NONANSWERED=
INBOUND_ANSWERED=
INBOUND_NONANSWERED=
TWO_WAY_AUDIO=
CALLER_ID=
QUEUE_ROUTING=
TRANSFERS=
DISPOSITIONS=
CALLBACKS=
RECORDINGS=

ODOO_SYNCHRONIZATION=
ODOO_DUPLICATE_PROTECTION=
N8N_CANARY=
EXTERNAL_CUSTOMER_MESSAGES=

MTLS=
SERVICE_AUTHENTICATION=
CROSS_BUSINESS_UNIT_DENIAL=
CROSS_CAMPAIGN_DENIAL=
SECRET_SCAN=
MONITORING=
RECONNECT=
ROLLBACK=

CARRIER_CHARGES_USD=
CUSTOMER_CALLS_PLACED=
UNAPPROVED_CALLS_PLACED=
PRODUCTION_OBJECTS_CHANGED=
PRODUCTION_ROUTING_CHANGED=

EVIDENCE_DIRECTORY=
TEST_TARGET_ALLOWLIST=
CALL_MATRIX_REPORT=
AUDIO_REPORT=
ODOO_REPORT=
SECURITY_REPORT=
MONITORING_REPORT=
ROLLBACK_REPORT=
FINAL_REPORT=
FINAL_REPORT_SHA256=

PRODUCTION_READY=NO
```

---

# 13. Paste-Ready Codex Mandate

Proceed autonomously with the bounded VoIP-to-Odoo acceptance test authorized by this document.

Do not place an external call until the exact originating DID and every destination number are entered into a protected allowlist and verified as non-customer controlled test endpoints.

Use only synthetic users, campaigns, queues, DIDs, endpoints, contacts, leads, callbacks, recordings, and Odoo records.

Use the approved campaign families:

- TL-TEST-OUT and TL-TEST-IN
- DEV-TEST-OUT and DEV-TEST-IN
- SCP-TEST-OUT and SCP-TEST-IN

Create missing synthetic fixtures only when no equivalent safe test fixture exists.

Maximum limits:

- ten total calls;
- five U.S. dollars total carrier charges;
- ten minutes per call;
- sixty-minute test window;
- two external-transfer tests;
- three callbacks;
- ten test recordings.

Require two controlled people or endpoints and confirmed recording consent.

Test inbound, outbound, two-way audio, caller ID, queue routing, transfers, dispositions, callbacks, recordings, Odoo synchronization, duplicate protection, permissions, monitoring, reconnect, and rollback.

Do not use customer numbers, customer leads, emergency numbers, premium-rate numbers, predictive dialing, unrestricted carrier routes, or unapproved external destinations.

Do not send customer email, SMS, social messages, or callbacks.

Abort and roll back immediately on any customer destination, unauthorized route, sensitive-field exposure, production mutation, missing event, duplicate business effect, monitoring failure, or rollback failure.

Correct defects autonomously and rerun affected tests within the approved limits.

Finish with all test campaigns inactive, test endpoints revoked or disabled, temporary credentials revoked, production routing unchanged, and `PRODUCTION_READY=NO`.

Return the complete evidence-backed final report.
