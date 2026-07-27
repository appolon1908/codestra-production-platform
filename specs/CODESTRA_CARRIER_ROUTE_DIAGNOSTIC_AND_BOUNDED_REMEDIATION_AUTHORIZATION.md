# Codestra Carrier Route Diagnostic and Bounded Remediation Authorization

## Change Identification

```text
CHANGE_ID=CHG-20260725-CARRIER-ROUTE-REMEDIATION-01
PARENT_CHANGE_ID=CHG-20260725-VOIP-ODOO-ACCEPTANCE-01
APPROVER=Ralph L. Appolon
APPROVAL_DATE=2026-07-25

ROOT_ENGINEERING_AUTHORIZED=YES
CARRIER_ACCOUNT_DIAGNOSTIC_AUTHORIZED=YES
BOUNDED_CARRIER_ROUTE_REMEDIATION_AUTHORIZED=YES
BOUNDED_EXTERNAL_RETEST_AUTHORIZED=YES
FULL_PRODUCTION_ACTIVATION_AUTHORIZED=NO
```

## Purpose

Resolve the existing outbound Twilio route failure that returned
`congested/circuit unavailable` for two calls placed only to the approved
controlled non-customer endpoint.

This authorization permits read-only carrier-account investigation and narrowly
scoped correction of the existing approved route. It does not authorize
unrestricted carrier changes, customer calling, public DID reassignment,
predictive dialing, or production activation.

---

# 1. Approved Test Targets

```text
APPROVED_ORIGINATING_TEST_DID=+16173419794
APPROVED_DESTINATION_1=+18492022053
EXTERNAL_TRANSFER_DESTINATION=+18492022053

DESTINATION_OWNER_OR_CUSTODIAN=Ralph Appolon
DESTINATION_CONFIRMED_NON_CUSTOMER=YES
DESTINATION_AUTHORIZED_FOR_TESTING=YES
RECORDING_CONSENT_CONFIRMED=YES
```

No other external number may be called.

Complete numbers must remain in protected root-only approval files. Reports and
ordinary logs must use masked values and hashes.

---

# 2. Remaining Limits

The prior acceptance evidence recorded five cumulative test-call attempts.

```text
PRIOR_CUMULATIVE_TEST_CALL_ATTEMPTS=5
MAXIMUM_TOTAL_TEST_CALL_ATTEMPTS=10
MAXIMUM_ADDITIONAL_CALL_ATTEMPTS=5
MAXIMUM_TOTAL_CARRIER_CHARGES_USD=5.00
MAXIMUM_SINGLE_CALL_DURATION_MINUTES=10
MAXIMUM_REMEDIATION_WINDOW_MINUTES=60
```

The total charge limit includes every call under the parent change.

Before another call:

- obtain carrier billing, pricing, balance, or usage evidence sufficient to
  prove the total authorized charge limit cannot be exceeded;
- stop when the current total cannot be bounded safely;
- stop automatically at five additional attempts or the charge limit.

---

# 3. Authorized Read-Only Carrier Diagnostics

Codex may inspect, without printing secrets:

- carrier account status;
- account suspension or restriction state;
- balance, credit, usage, and current test-call charges;
- SIP trunk status;
- termination domain or URI;
- authentication method;
- credential-list references;
- IP access-control list references;
- source IP authorization;
- geographic calling permissions;
- destination-country permission;
- caller-ID ownership and authorization;
- verified caller-ID status where applicable;
- trunk origination and termination settings;
- number normalization and E.164 formatting;
- Asterisk route selection;
- dial string;
- transport;
- codec negotiation;
- SIP response code;
- Q.850 cause code;
- carrier call or debug logs for the two rejected attempts;
- account concurrency and call-per-second limits;
- fraud-protection or destination-risk blocks;
- rate or destination availability;
- applicable carrier status indicators.

Do not expose:

- account authentication tokens;
- API keys;
- SIP passwords;
- Authorization headers;
- credential-list values;
- full telephone numbers in ordinary evidence;
- customer data.

---

# 4. Authorized Bounded Remediation

Codex may correct only the existing approved outbound test route when the defect
is proven.

Permitted corrections include:

- correcting the existing trunk or termination URI reference;
- correcting E.164 number formatting;
- correcting the current Asterisk dial-string syntax;
- correcting the existing trunk peer reference;
- correcting the existing carrier authentication reference;
- attaching the existing approved source IP to the intended ACL;
- attaching the intended credential-list reference;
- enabling the specific approved destination geography when account policy and
  owner authorization permit it;
- enabling the approved originating caller ID when ownership is proven;
- correcting transport or codec configuration needed by the existing carrier;
- correcting a route pattern so that only the approved test destination is
  eligible during the bounded test window;
- reloading Asterisk SIP/PJSIP or dialplan configuration without restarting
  Asterisk;
- restarting only a dedicated carrier adapter or proxy when proven necessary
  and after checkpoint creation.

Any change must be:

- narrowly scoped;
- backed up first;
- checksum recorded;
- test-target constrained;
- automatically reversible;
- applied during the bounded window;
- verified after rollback or cleanup.

---

# 5. Explicitly Prohibited Actions

Do not:

- purchase a new DID;
- reassign the production DID;
- change inbound production routing;
- change `CS_SALES` or the production main IVR;
- activate predictive dialing;
- enable customer campaigns;
- call customer numbers;
- expand the destination allowlist;
- change account-wide carrier credentials unless they are proven compromised;
- rotate unrelated carrier secrets;
- modify unrelated trunks;
- disable fraud controls globally;
- enable unrestricted international calling;
- remove emergency-number protections;
- increase spending limits;
- activate persistent event delivery;
- enable `SEND_EVENTS=true`;
- enable worker boot persistence;
- activate production operation.

---

# 6. Mandatory Preflight

Before mutation:

```text
AUTHORIZATION_VERIFIED=PASS
PROJECT_LOCKS=PASS
ROLLBACK_CHECKPOINT=PASS

ASTERISK_ACTIVE=active
ACTIVE_PRODUCTION_CALLS=0
QUEUED_PRODUCTION_CALLS=0
LIVE_PRODUCTION_AGENTS=0

PROTECTED_ALLOWLIST=PASS
ALLOWLIST_EXACT_MATCH=PASS
DESTINATION_CUSTOMER_LEADS=0

SEND_EVENTS=false
WORKER_BOOT_PERSISTENCE=DISABLED
KILL_SWITCH=active
```

Carrier-access preflight must establish:

```text
CARRIER_ACCOUNT_ACCESS=PASS
CARRIER_ACCOUNT_STATUS=ACTIVE
CARRIER_BILLING_EVIDENCE=PASS
CARRIER_TOTAL_TEST_CHARGES_USD=
CARRIER_REMAINING_AUTHORIZED_BUDGET_USD=
ORIGINATING_CALLER_ID_AUTHORIZED=PASS
DESTINATION_GEOGRAPHY_ALLOWED=PASS
SOURCE_IP_OR_CREDENTIAL_AUTH=PASS
```

Do not make another external attempt when carrier billing evidence is absent.

---

# 7. Required Diagnostic Classification

Classify the two existing rejected attempts using carrier and Asterisk evidence.

Return:

```text
ATTEMPT_1_CARRIER_CALL_ID_HASH=
ATTEMPT_1_SIP_RESPONSE_CODE=
ATTEMPT_1_Q850_CAUSE=
ATTEMPT_1_CLASSIFICATION=

ATTEMPT_2_CARRIER_CALL_ID_HASH=
ATTEMPT_2_SIP_RESPONSE_CODE=
ATTEMPT_2_Q850_CAUSE=
ATTEMPT_2_CLASSIFICATION=

ROOT_CAUSE=
REMEDIATION_REQUIRED=
```

Do not fabricate missing carrier data.

---

# 8. Bounded Retest

After the root cause is proven and corrected:

1. Verify the allowlist again.
2. Verify zero active and queued production calls.
3. Verify the cost counter.
4. Place one short outbound test call to the approved destination.
5. Stop and reconcile before any additional attempt.
6. Continue only when the previous attempt is understood.
7. Do not exceed five additional attempts.

Required scenarios, as available within the remaining budget:

- one answered call;
- caller-ID presentation;
- two-way audio;
- consented recording;
- one approved external transfer;
- one inbound test only when it requires no prohibited production-routing
  mutation.

Do not repeat known-failing attempts without a corrective action.

---

# 9. Immediate Abort Triggers

Abort and roll back for:

- destination outside the allowlist;
- missing carrier billing evidence;
- charge-limit uncertainty;
- account suspension;
- credential exposure;
- unauthorized geographic expansion;
- production routing mutation;
- public DID reassignment;
- customer interaction;
- emergency or premium destination;
- one-way audio;
- duplicate external attempt without corrective action;
- monitoring failure;
- rollback failure;
- active production call appearing during the test;
- carrier or Asterisk health degradation.

---

# 10. Rollback and Final State

After PASS or abort:

```text
ALLOWLIST_FINAL=EXPIRED_REMOVED
TEST_CALL_COUNTER_FINAL=REMOVED_OR_ARCHIVED_RESTRICTED
TEMPORARY_ROUTE_RULES_FINAL=REMOVED
TEMPORARY_CREDENTIALS_FINAL=REVOKED
PRODUCTION_ROUTING_CHANGED=NO
PUBLIC_DIDS_CHANGED=NO
UNRELATED_CARRIERS_CHANGED=NO

SEND_EVENTS=false
WORKER_BOOT_PERSISTENCE=DISABLED
KILL_SWITCH=active
ACTIVE_CHANNELS_FINAL=0
ACTIVE_CALLS_FINAL=0
PRODUCTION_READY=NO
```

A carrier correction may remain only when it is the reviewed correction to the
existing intended production trunk and its rollback, security, monitoring, and
owner approval evidence all pass. Otherwise restore the pre-change checkpoint.

---

# 11. Required Final Report

```text
CHANGE_ID=CHG-20260725-CARRIER-ROUTE-REMEDIATION-01
OVERALL_STATUS=

AUTHORIZATION_SHA256=
PROJECT_LOCKS=
ROLLBACK_CHECKPOINT=

CARRIER_ACCOUNT_ACCESS=
CARRIER_ACCOUNT_STATUS=
CARRIER_BILLING_EVIDENCE=
CARRIER_TOTAL_TEST_CHARGES_USD=
CARRIER_REMAINING_AUTHORIZED_BUDGET_USD=

EXISTING_ATTEMPTS_CLASSIFIED=
ROOT_CAUSE=
FILES_CHANGED=
CARRIER_SETTINGS_CHANGED=
ASTERISK_SETTINGS_CHANGED=
BEFORE_AFTER_CHECKSUMS=

ADDITIONAL_EXTERNAL_ATTEMPTS=
CUMULATIVE_TEST_CALL_ATTEMPTS=
EXTERNAL_CALLS_ANSWERED=
CALLER_ID_PRESENTATION=
TWO_WAY_AUDIO=
TEST_RECORDING=
EXTERNAL_TRANSFER=
INBOUND_EXTERNAL_TEST=

CUSTOMER_CALLS_PLACED=
UNAPPROVED_CALLS_PLACED=
EMERGENCY_CALLS_PLACED=
PREMIUM_RATE_CALLS_PLACED=
CARRIER_CHARGES_USD=

ROLLBACK_TRIGGERED=
ROLLBACK_RESULT=
FINAL_CONTROLS=

EVIDENCE_DIRECTORY=
CARRIER_DIAGNOSTIC_REPORT=
CARRIER_BILLING_REPORT=
CALL_REPORT=
AUDIO_REPORT=
RECORDING_REPORT=
ROLLBACK_REPORT=
FINAL_REPORT=
FINAL_REPORT_SHA256=

PRODUCTION_READY=NO
```

---

# 12. Paste-Ready Codex Mandate

Proceed autonomously with the bounded carrier-route diagnostic and remediation
authorized by this document.

Orchestrate from Server A and use the approved Server A-to-Server B SSH path.

Do not require Server B-to-Server A SSH.

First authenticate the authorization, protected allowlist, project locks, and
rollback checkpoint.

Inspect the two existing Twilio rejections and obtain carrier account, call-log,
geographic-permission, caller-ID, source-authentication, balance, pricing, and
billing evidence without printing secrets.

Do not make another call until carrier billing evidence proves the total
US$5.00 charge ceiling can be respected.

Correct only a proven defect in the existing approved outbound route. Do not
change production inbound routing, the production main IVR, `CS_SALES`, public
DID assignments, customer campaigns, predictive dialing, or unrelated carrier
settings.

Use only:

- originating DID `+16173419794`;
- controlled destination `+18492022053`;
- owner/custodian `Ralph Appolon`.

Do not call any other number.

The cumulative call limit is ten. Five attempts have already been consumed, so
no more than five additional attempts are authorized.

After a proven correction, place one call at a time, reconcile it completely,
and continue only when the previous result is understood.

Abort immediately for missing billing evidence, any destination mismatch,
credential exposure, unauthorized route expansion, production mutation,
customer interaction, charge uncertainty, monitoring failure, or rollback
failure.

Finish fail-closed with persistent event delivery disabled and
`PRODUCTION_READY=NO`.

Return the complete checksummed evidence-backed final report.
