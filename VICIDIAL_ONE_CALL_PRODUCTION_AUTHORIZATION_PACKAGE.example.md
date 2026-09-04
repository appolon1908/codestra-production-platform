# VICIdial One-Call Production Authorization Package

Complete this private package before either server may arm production. Do not
publish the real destination, credentials, or private policy documents in a
public repository or public evidence report.

## 0. Draft status and source boundary

This is an unsigned preparation draft, not an approval or an executable
configuration. Keep the completed private copy at the existing approved private
location; do not overwrite any newer signed package with this example. The
runtime filename `VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.md` must
remain outside Git. Commit only this `.example.md` file and sanitized evidence.
Never place a real destination, its fingerprint, credentials, signatures, or
private policy contents in Git or public CI artifacts.

Prepared on 2026-09-04 from the saved authorization form and the repository
readiness report at `e44decce67b8bc292753d77a82ca21c9fa37af0f`:
`reports/app-server-a/PRODUCTION_CALLING_READINESS_20260904.md`.
That repository SHA is a document source, not an approved runtime target.
Historical source approvals, event-change IDs, event counts, and PASS labels
from the saved form have not been carried forward as current evidence.

```text
PACKAGE_STATE=DRAFT_BLOCKED
PACKAGE_SIGNED=NO
RUNTIME_STATE_VERIFIED_THIS_SESSION=NO
REQUIRED_BASELINE_ENABLE_VICIDIAL_WRITES=false
REQUIRED_BASELINE_SEND_EVENTS=false
```

Blank fields and `NOT_TESTED` entries are unresolved gates. The requested
execution sequence is not a substitute for named, scope-bound approval.

## 1. Fixed system identity

```text
SYSTEM_NAME=Codestra VICIdial -> Middleware -> Odoo/n8n
SERVER_A_PUBLIC_IP=65.109.65.169
SERVER_A_PRIVATE_IP=10.40.0.1
SERVER_A_ROLE=Middleware/Odoo/PostgreSQL/Redis/n8n
SERVER_A_EXISTING_APPROVED_TARGET=
SERVER_B_PUBLIC_IP=65.21.67.207
SERVER_B_PRIVATE_IP=10.40.0.2
SERVER_B_ROLE=VICIdial/Asterisk/SIP/event publisher
SERVER_B_EXISTING_APPROVED_TARGET=
CURRENT_EVENT_CHANGE_ID=
CURRENT_EVENT_CHANGE_SCOPE=
```

If source remediation creates new protected-release commits, replace the
applicable approved targets above and attach exact review/merge/approval evidence.

## 2. One-call change authorization

The existing event-only change does not by itself authorize a live call. Fill
one of these:

```text
ONE_CALL_CHANGE_ID=
ONE_CALL_CHANGE_TYPE=NEW_CHANGE_OR_APPROVED_SCOPE_AMENDMENT
ONE_CALL_CHANGE_RECORD_URL_OR_REFERENCE=
CHANGE_APPROVAL_TIMESTAMP_UTC=
CHANGE_EXPIRY_UTC=
CHANGE_STATUS=PENDING
```

The change record must explicitly authorize exactly one manual live call and
the exact resources below.

## 3. VICIdial pilot scope

```text
PILOT_CAMPAIGN_ID=
PILOT_LIST_ID=
PILOT_USER_GROUP=
APPROVED_OPERATOR_ID=
APPROVED_EXTENSION=
DIAL_METHOD=MANUAL
MAX_HOPPER=1
MAX_CALLS=1
MAX_CONCURRENT_CALLS=1
MAX_CALL_DURATION_SECONDS=
RETRY_CALLS_AUTHORIZED=NO
CUSTOMER_LISTS_PERMISSION=DENIED
UNRELATED_CAMPAIGNS_PERMISSION=DENIED
PILOT_LIST_MEMBERSHIP_READBACK_REFERENCE=
PREDICTIVE_DIALING=DENIED
AUTOMATED_DIALING=DENIED
```

## 4. Destination and routing

Keep the actual E.164 destination private.

```text
DESTINATION_ALLOWLIST_E164=
DESTINATION_OWNER_OR_TEST_CONTROLLER=
DESTINATION_CONTROL_EVIDENCE=
DESTINATION_FINGERPRINT_SHA256=
PERMITTED_COUNTRY=
PERMITTED_DESTINATION_CLASS=
APPROVED_CALLER_ID_DID=
CALLER_ID_CONTROL_EVIDENCE=
CALLER_ID_FINGERPRINT_SHA256=
APPROVED_SIP_TRUNK_ID=
APPROVED_CARRIER=
TRUNK_CONTROL_EVIDENCE=
ROUTE_FALLBACK=DENIED
```

## 5. Calling window and rollback

```text
CALLING_TIMEZONE=
LEGAL_CALLING_HOURS_LOCAL=
ACTIVATION_START_UTC=
ACTIVATION_END_UTC=
ROLLBACK_DEADLINE_UTC=
MAX_CANARY_DURATION_MINUTES=
ROLLBACK_AUTHORITY_NAME=
ROLLBACK_AUTHORITY_CONTACT_REFERENCE=
ROLLBACK_AUTHORITY_AVAILABLE_DURING_WINDOW=NOT_TESTED
```

The activation window must also fall inside the approved legal calling hours.

## 6. Consent, DNC, privacy, and recording

```text
CONSENT_POLICY_ID_VERSION=
CONSENT_EVIDENCE_REFERENCE_FOR_DESTINATION=
CONSENT_CHECK_RESULT=NOT_TESTED
PERMANENT_DNC_POLICY_ID_VERSION=
PERMANENT_DNC_CHECK_REFERENCE=
PERMANENT_DNC_CHECK_RESULT=NOT_TESTED
INTERNAL_DNC_CHECK_RESULT=NOT_TESTED
RECORDING_POLICY_ID_VERSION=
RECORDING_ENABLED_FOR_CANARY=
RECORDING_ANNOUNCEMENT_OR_CONSENT_METHOD=
RECORDING_RETENTION=
RECORDING_CONTENT_ACCESS_PERMISSION=DENIED
PRIVACY_DATA_MINIMIZATION_REFERENCE=
```

Any missing or indeterminate consent/DNC value is a denial.

## 7. Callback, appointment, transfer, and communications

All capabilities below remain `DENIED` for this one-call mission.

```text
CALLBACK_PERMISSION=DENIED
APPOINTMENT_PERMISSION=DENIED
TRANSFER_PERMISSION=DENIED
SMS_PERMISSION=DENIED
EMAIL_PERMISSION=DENIED
VOICEMAIL_DROP_PERMISSION=DENIED
CUSTOMER_WEBHOOK_PERMISSION=DENIED
N8N_CUSTOMER_COMMUNICATION=DENIED
```

Any value other than `DENIED` invalidates this package for the requested
one-call scope. Expanded testing requires a separate bounded authorization;
do not enable these capabilities under this mission.

## 8. Odoo production mapping

```text
ODOO_DATABASE=
ODOO_COMPANY_ID=
ODOO_COMPANY_NAME=
ODOO_BUSINESS_UNIT_ID_OR_NAME=
ODOO_CRM_TEAM_ID=
ODOO_PIPELINE_ID_OR_NAME=
ODOO_INITIAL_STAGE_ID=
ODOO_CAMPAIGN_ID_OR_BINDING=
ODOO_LEAD_OR_OPPORTUNITY_MODEL=
ODOO_CALL_RESULT_MODEL=
ODOO_MAPPING_SCHEMA_VERSION=
ODOO_TENANT_OR_COMPANY_ISOLATION_RULE=
ODOO_IDEMPOTENCY_KEY_FORMAT=
ODOO_MAPPING_OWNER=
ODOO_MAPPING_APPROVER=
```

Complete all 11 disposition mappings required by the saved form and attach
their certification evidence; do not assume they are already certified:

| # | VICIdial disposition code | Odoo result/stage/action | Required fields | Customer communication allowed? | Approved |
|---:|---|---|---|---|---|
| 1 |  |  |  | No |  |
| 2 |  |  |  | No |  |
| 3 |  |  |  | No |  |
| 4 |  |  |  | No |  |
| 5 |  |  |  | No |  |
| 6 |  |  |  | No |  |
| 7 |  |  |  | No |  |
| 8 |  |  |  | No |  |
| 9 |  |  |  | No |  |
| 10 |  |  |  | No |  |
| 11 |  |  |  | No |  |

Unknown dispositions must fail closed and create no partial CRM mutation.

## 9. n8n canary

```text
N8N_CANARY_WORKFLOW_ID=
N8N_CANARY_WORKFLOW_NAME=
N8N_CANARY_WORKFLOW_ACTIVE=NO
N8N_OUTBOUND_NODES_DISABLED=NOT_TESTED
N8N_CUSTOMER_CREDENTIALS_UNAVAILABLE_TO_CANARY=NOT_TESTED
N8N_EXPECTED_AUDIT_ONLY_RESULT=
N8N_OWNER=
N8N_APPROVER=
```

## 10. Historical event decision

Fresh read-only inventory is required; do not reuse historical counts:

```text
QUARANTINED_EVENTS=
ARCHIVED_EVENTS=
HISTORICAL_REPLAY_AUTHORIZED=NO
```

Recommended safe decision:

```text
HISTORICAL_EVENT_DISPOSITION=RETAIN_LOCKED_NO_REPLAY_PENDING_APPROVAL
HISTORICAL_RETENTION_POLICY_ID_VERSION=
HISTORICAL_DISPOSITION_LEDGER_REFERENCE=
HISTORICAL_DISPOSITION_APPROVER=
HISTORICAL_DISPOSITION_APPROVAL_TIMESTAMP_UTC=
```

If any individual record may be replayed, do not approve it in this package.
Use a separate record-specific change with idempotency proof, customer-impact
analysis, exact record hash, and individual approvers.

## 11. Backup authorization

Do not place private keys in this document.

```text
SERVER_B_BACKUP_REMOTE_HOST_OR_PRIVATE_ENDPOINT=
SERVER_B_BACKUP_PINNED_HOST_KEY_FINGERPRINT=
SERVER_B_BACKUP_RESTRICTED_ACCOUNT=
SERVER_B_BACKUP_RESTRICTED_PATH=
SERVER_B_BACKUP_PUBLIC_KEY_FINGERPRINT=
SERVER_B_BACKUP_PUBLIC_KEY_AUTHORIZED=NOT_TESTED
SERVER_B_BACKUP_ENCRYPTION_POLICY=
SERVER_B_BACKUP_RETENTION_POLICY=
SERVER_B_BACKUP_QUOTA=
SERVER_B_BACKUP_RESTORE_OWNER=
SERVER_B_BACKUP_AUTHORIZER=
SERVER_B_BACKUP_AUTHORIZATION_TIMESTAMP_UTC=

SERVER_A_BACKUP_REMOTE_HOST_OR_PRIVATE_ENDPOINT=
SERVER_A_BACKUP_RESTRICTED_ACCOUNT_AND_PATH=
SERVER_A_BACKUP_PUBLIC_KEY_FINGERPRINT=
SERVER_A_BACKUP_PUBLIC_KEY_AUTHORIZED=NOT_TESTED
SERVER_A_BACKUP_ENCRYPTION_AND_RETENTION_POLICY=
SERVER_A_BACKUP_RESTORE_OWNER=
SERVER_A_BACKUP_AUTHORIZER=
SERVER_A_FRESH_BACKUP_MANIFEST_REFERENCE=
SERVER_A_BACKUP_CREATED_AT_UTC=
SERVER_A_BACKUP_INTEGRITY_REFERENCE=
SERVER_A_OFFHOST_BACKUP_REFERENCE=
SERVER_A_ISOLATED_RESTORE_PROOF_REFERENCE=
SERVER_B_FRESH_BACKUP_MANIFEST_REFERENCE=
SERVER_B_BACKUP_CREATED_AT_UTC=
SERVER_B_BACKUP_INTEGRITY_REFERENCE=
SERVER_B_OFFHOST_BACKUP_REFERENCE=
SERVER_B_ISOLATED_RESTORE_PROOF_REFERENCE=
PAIRED_BACKUP_CONSISTENCY_REFERENCE=
ROLLBACK_RUNBOOK_REFERENCE=
PREVIOUS_EXACT_SOURCE_AND_DIGEST_TUPLE_REFERENCE=
ROLLBACK_REHEARSAL_REFERENCE=
```

## 12. Required named approvals

Each approver must approve this exact package version and the final canonical
manifest hash. One person may hold multiple roles only if company policy permits
it; record every role separately.

```text
BUSINESS_APPROVER_NAME=
BUSINESS_APPROVAL_REFERENCE=
BUSINESS_APPROVAL_TIMESTAMP_UTC=

COMPLIANCE_PRIVACY_APPROVER_NAME=
COMPLIANCE_PRIVACY_APPROVAL_REFERENCE=
COMPLIANCE_PRIVACY_APPROVAL_TIMESTAMP_UTC=

SECURITY_APPROVER_NAME=
SECURITY_APPROVAL_REFERENCE=
SECURITY_APPROVAL_TIMESTAMP_UTC=

OPERATIONS_APPROVER_NAME=
OPERATIONS_APPROVAL_REFERENCE=
OPERATIONS_APPROVAL_TIMESTAMP_UTC=

TELEPHONY_APPROVER_NAME=
TELEPHONY_APPROVAL_REFERENCE=
TELEPHONY_APPROVAL_TIMESTAMP_UTC=

ODOO_APPROVER_NAME=
ODOO_APPROVAL_REFERENCE=
ODOO_APPROVAL_TIMESTAMP_UTC=

N8N_APPROVER_NAME=
N8N_APPROVAL_REFERENCE=
N8N_APPROVAL_TIMESTAMP_UTC=

RELEASE_APPROVER_NAME=
RELEASE_APPROVAL_REFERENCE=
RELEASE_APPROVAL_TIMESTAMP_UTC=

ROLLBACK_APPROVER_NAME=
ROLLBACK_APPROVAL_REFERENCE=
ROLLBACK_APPROVAL_TIMESTAMP_UTC=
```

## 13. Canonical approval manifest

After all fields and approvals are complete:

```text
PACKAGE_VERSION=
PACKAGE_FINALIZED_AT_UTC=
PACKAGE_CANONICALIZATION_METHOD=UTF8_LF_SORTED_KEYS_OR_APPROVED_EQUIVALENT
APPROVAL_MANIFEST_SHA256=
SERVER_A_MANIFEST_SHA256_VERIFIED=NOT_TESTED
SERVER_B_MANIFEST_SHA256_VERIFIED=NOT_TESTED
ALL_MANDATORY_FIELDS_COMPLETE=NO
ALL_REQUIRED_APPROVALS_VALID=NO
AUTHORIZATION_DECISION=BLOCKED
```

Any change to campaign, list, operator, extension, destination, caller ID,
trunk, country/class, window, policy, Odoo mapping, n8n workflow, artifact target,
or approver invalidates the hash and requires a new approval.

## 14. Final pre-call signoff

```text
SERVER_A_READY_FOR_CALL=NOT_TESTED
SERVER_B_READY_FOR_CALL=NOT_TESTED
SERVER_A_SERVER_B_MANIFEST_HASH_MATCH=NOT_TESTED
PROVENANCE_ALL_COMPONENTS=NOT_TESTED
OFFSERVER_BACKUP_AND_RESTORE_BOTH_SERVERS=NOT_TESTED
MONITORING_AND_ALERT_RECOVERY_BOTH_SERVERS=NOT_TESTED
ODOO_MAPPING_DISABLED_DRY_RUN=NOT_TESTED
N8N_INACTIVE_NO_MESSAGE_CANARY=NOT_TESTED
HISTORICAL_EVENTS_LOCKED_NO_REPLAY=NOT_TESTED
CONSENT_AND_DNC_RECHECK=NOT_TESTED
CURRENT_TIME_INSIDE_APPROVED_WINDOW=NOT_TESTED
ROLLBACK_AUTHORITIES_AVAILABLE=NOT_TESTED
FINAL_GO_FOR_ONE_CALL_BY=
FINAL_GO_TIMESTAMP_UTC=
```

All named gate results above must become `PASS` on fresh evidence. The final
GO name and timestamp must also be completed and valid. Any missing value
blocks the call. A template check or document review is not runtime preflight.

## 15. Final technical preflight and bounded activation

Collect the following on both servers during the approved window. Do not
substitute health endpoints for policy, identity, or business-state checks.
Use the deployed, versioned API contracts; do not invent execution endpoints.

```text
ODOO_CAMPAIGN_MAPPING_READBACK_REFERENCE=
MIDDLEWARE_AUTHORIZATION_POLICY_REFERENCE=
MIDDLEWARE_IDEMPOTENCY_NEGATIVE_TEST_REFERENCE=
KONG_CADDY_ROUTE_AND_AUTHENTICATION_REFERENCE=
VICIDIAL_ADAPTER_READBACK_REFERENCE=
CALLING_WINDOW_CONSENT_DNC_RECHECK_REFERENCE=
MONITORING_BASELINE_AND_KILL_SWITCH_REFERENCE=
EXACT_RUNTIME_SOURCE_AND_IMAGE_DIGEST_READBACK_REFERENCE=
PRECALL_SIDE_EFFECT_COUNTER_SNAPSHOT_REFERENCE=
APPROVED_MINIMUM_FLAG_DIFF_REFERENCE=
CAMPAIGN_DESTINATION_SCOPED_ENFORCEMENT_REFERENCE=
ATOMIC_ONE_ATTEMPT_BUDGET_REFERENCE=
AUTOMATIC_FAIL_CLOSED_EXPIRY_REFERENCE=
```

The pilot list must contain only the single controlled destination. Customer
lists, other campaigns, predictive/automated dialing, callbacks, appointments,
transfers, SMS, email, voicemail drops, customer webhooks, and n8n customer
communication remain disabled. Do not globally enable an event backlog to
reconcile this call. Isolate only its approved event IDs, and leave historical
quarantine/archive records locked without replay.

Before arming, confirm both servers independently validate the same approved
manifest hash and exact source/image tuple. Install and verify the approved
expiry/kill-switch mechanism and reserve one durable call-attempt budget.
A failed or ambiguous call attempt still consumes that budget. Never redial or
retry automatically. If campaign/destination scoping cannot be enforced, do not
substitute global flag enablement. Keep fail-closed and issue NO-GO.

## 16. One-call execution and reconciliation evidence

These fields are intentionally empty until an authorized call occurs. Do not
manufacture IDs or insert a synthetic Odoo call record as evidence of a live call.

```text
CALL_ATTEMPT_STARTED_AT_UTC=
CALL_ATTEMPT_FINISHED_AT_UTC=
CALL_ATTEMPTS_CONSUMED=
ASTERISK_UNIQUEID=
ASTERISK_LINKEDID=
VICIDIAL_CALL_ID=
VICIDIAL_LEAD_ID=
MIDDLEWARE_CORRELATION_ID=
MIDDLEWARE_EVENT_IDS=
MIDDLEWARE_IDEMPOTENCY_KEY_REFERENCE=
ODOO_CALL_RECORD_MODEL=
ODOO_CALL_RECORD_ID=
FINAL_DISPOSITION_CODE=
DISPOSITION_MAPPING_READBACK_REFERENCE=
RECORDING_POLICY_ENFORCEMENT_REFERENCE=
POSTCALL_SIDE_EFFECT_COUNTER_SNAPSHOT_REFERENCE=
DUPLICATE_SIDE_EFFECT_CHECK_REFERENCE=
CALL_RECONCILIATION_RESULT=NOT_TESTED
```

Reconcile the single call across the exact tenant/company/campaign and approved
agent. Preserve events and audit history. Do not replay the dialing request to
test idempotency. Verify zero duplicate leads/call records, zero extra dialing,
and zero callback, transfer, customer-message, or recording-content access
side effects. Recording creation must match the approved recording policy.

## 17. Disarm, read-back, and limited-production decision

Disarm immediately when the call terminates, a gate fails, monitoring is lost,
the approved window expires, or the attempt's outcome is uncertain. Do not leave
call-capable flags enabled while waiting for downstream reconciliation. Preserve
bounded read-only evidence access without enabling historical delivery/replay.
Restore the verified pre-call fail-closed configuration and read it back from
both servers, not just an environment file. Do not restore a database over live
production merely to erase call evidence; preserve history and use the approved
rollback procedure.

```text
FAIL_CLOSED_RESTORED_AT_UTC=
SERVER_A_FAIL_CLOSED_READBACK_REFERENCE=
SERVER_B_FAIL_CLOSED_READBACK_REFERENCE=
NO_RESIDUAL_CALL_OR_QUEUED_SIDE_EFFECT_REFERENCE=
POSTCALL_MONITORING_REFERENCE=
ROLLBACK_EXECUTION_REFERENCE=
FINAL_EVIDENCE_BUNDLE_REFERENCE=
FINAL_EVIDENCE_SHA256=
ONE_CALL_ASSESSMENT=NO_GO_PENDING_EVIDENCE
LIMITED_PRODUCTION_DECISION=NO_GO
LIMITED_PRODUCTION_DECISION_OWNER=
LIMITED_PRODUCTION_DECISION_TIMESTAMP_UTC=
SEPARATE_LIMITED_PRODUCTION_AUTHORIZATION_REFERENCE=
```

A successful controlled call supports an evidence review only. It does not
implicitly authorize persistent flags, customer lists, higher volume, or any
excluded capability. Limited production requires a separate bounded, signed
release; until then, both servers remain fail-closed.
