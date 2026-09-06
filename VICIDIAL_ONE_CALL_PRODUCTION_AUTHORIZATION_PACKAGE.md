# VICIdial One-Call Production Authorization Package

**PACKAGE_STATE=DRAFT_BLOCKED. This is an unsigned, sanitized preparation copy,
not permission to arm either server and not proof of a completed call.**

Prepared on 2026-09-04 from the saved package of the same name. Its fourteen
original sections are retained. Missing pilot values have not been invented.
Prefilled PASS/YES/APPROVED attestations have been reset where no supporting
current evidence was supplied. Denied capabilities and the one-call cap remain.

The requested server path is
`/root/codestra-production-completion/VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.md`.
The original server-local file was not read or overwritten: the connected-host
inventory returned no hosts. This Git copy must remain sanitized. Complete the
private operator copy in protected storage, outside the tracked working tree;
do not commit real phone numbers, credentials, signatures or private evidence.

Preparation is not authorization. The request to execute this procedure does
not supply the destination, calling window, independent approvals or runtime
proof. The current decision is **NO-GO for the call and limited production**.


Complete this private package before either server may arm production. Do not
publish the real destination, credentials, or private policy documents in a
public repository or public evidence report.

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
CURRENT_EVENT_CHANGE_ID=CHG-20260725-VICIDIAL-EVENT-PRODUCTION-CUTOVER-01
CURRENT_EVENT_CHANGE_SCOPE=LIMITED_EVENT_CUTOVER_ONLY
```

Historical targets in the saved source were Server A
`1ea3a0ad86b35b74b80aaa3308050e496c21d756` and Server B
`b7ffe4d60a364f00411852aa327e2c424fb2f56a`. They are retained here only as history,
not adopted as currently approved or deployed targets. The observed platform
branch head `e44decce67b8bc292753d77a82ca21c9fa37af0f` is also not runtime proof.
Actual deployment SHAs and immutable image digests need authenticated readback
and exact review/release evidence before the pilot package can be finalized.

If source remediation creates new protected-main SHAs, replace the applicable
approved targets above and attach the exact review/merge/approval evidence.

## 2. One-call change authorization

The existing event-only change does not by itself authorize a live call. Fill
one of these:

```text
ONE_CALL_CHANGE_ID=
ONE_CALL_CHANGE_TYPE=NEW_CHANGE_OR_APPROVED_SCOPE_AMENDMENT
ONE_CALL_CHANGE_RECORD_URL_OR_REFERENCE=
CHANGE_APPROVAL_TIMESTAMP_UTC=
CHANGE_EXPIRY_UTC=
CHANGE_STATUS=NOT_PROVIDED
```

The change record must explicitly authorize exactly one manual live call and
the exact resources below. Missing, expired or inaccessible approvals block the
call. An instruction to deploy, a PR approval, or an event-only authorization
is not substituted for business, compliance, security, release or rollback
approval. The named roles in section 12 must approve the same finalized scope.

## 3. VICIdial pilot scope

```text
PILOT_CAMPAIGN_ID=
PILOT_LIST_ID=
PILOT_USER_GROUP=
APPROVED_OPERATOR_ID=
APPROVED_EXTENSION=
DIAL_METHOD=MANUAL
MAX_HOPPER=1
INITIAL_HOPPER=0
MAX_CALLS=1
MAX_CALL_ATTEMPTS=1
MAX_CONCURRENT_CALLS=1
RETRY_CALLS_AUTHORIZED=NO
MAX_CALL_DURATION_SECONDS=
CUSTOMER_LISTS_PERMISSION=DENIED
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
ROLLBACK_AUTHORITY_AVAILABLE_DURING_WINDOW=NOT_VERIFIED
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
RECORDING_ENABLED_FOR_CANARY=YES_OR_NO
RECORDING_ANNOUNCEMENT_OR_CONSENT_METHOD=
RECORDING_RETENTION=
PRIVACY_DATA_MINIMIZATION_REFERENCE=
```

Any missing or indeterminate consent/DNC value is a denial.

## 7. Callback, appointment, transfer, and communications

Use `DENIED` unless the one-call test specifically needs and approves the
capability.

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

If any value is not `DENIED`, attach exact bounded scope, destination, operator,
workflow, content, window, consent, rollback, and named approval. That expanded
test is not automatically part of the initial one-call mission.

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

Attach the deterministic field mapping and bind all 11 certified dispositions:

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
N8N_OUTBOUND_NODES_DISABLED=NOT_VERIFIED
N8N_CUSTOMER_CREDENTIALS_UNAVAILABLE_TO_CANARY=NOT_VERIFIED
N8N_EXPECTED_AUDIT_ONLY_RESULT=
N8N_OWNER=
N8N_APPROVER=
```

## 10. Historical event decision

Historical record counts in the saved package were 51 quarantined and 2 archived;
these are not current observations. Current values require fresh readback:

```text
QUARANTINED_EVENTS=NOT_OBSERVED
ARCHIVED_EVENTS=NOT_OBSERVED
HISTORICAL_REPLAY_AUTHORIZED=NO
```

No historical replay is permitted by this pilot. Retention approval is still required:

```text
HISTORICAL_EVENT_DISPOSITION=NOT_APPROVED
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
SERVER_B_BACKUP_PUBLIC_KEY_AUTHORIZED=NOT_VERIFIED
SERVER_B_BACKUP_ENCRYPTION_POLICY=
SERVER_B_BACKUP_RETENTION_POLICY=
SERVER_B_BACKUP_QUOTA=
SERVER_B_BACKUP_RESTORE_OWNER=
SERVER_B_BACKUP_AUTHORIZER=
SERVER_B_BACKUP_AUTHORIZATION_TIMESTAMP_UTC=

SERVER_A_BACKUP_REMOTE_HOST_OR_PRIVATE_ENDPOINT=
SERVER_A_BACKUP_RESTRICTED_ACCOUNT_AND_PATH=
SERVER_A_BACKUP_PUBLIC_KEY_FINGERPRINT=
SERVER_A_BACKUP_PUBLIC_KEY_AUTHORIZED=NOT_VERIFIED
SERVER_A_BACKUP_ENCRYPTION_AND_RETENTION_POLICY=
SERVER_A_BACKUP_RESTORE_OWNER=
SERVER_A_BACKUP_AUTHORIZER=
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
PACKAGE_VERSION=2-DRAFT-20260904
PACKAGE_FINALIZED_AT_UTC=
PACKAGE_CANONICALIZATION_METHOD=UTF8_LF_SORTED_KEY_VALUE_LINES_V1
APPROVAL_MANIFEST_SHA256=
SERVER_A_MANIFEST_SHA256_VERIFIED=NOT_VERIFIED
SERVER_B_MANIFEST_SHA256_VERIFIED=NOT_VERIFIED
ALL_MANDATORY_FIELDS_COMPLETE=NO
ALL_REQUIRED_APPROVALS_VALID=NOT_VERIFIED
AUTHORIZATION_DECISION=BLOCKED
```

The canonical manifest input is the UTF-8 encoding, with no BOM, of every `KEY=VALUE`
line from sections 1–14 except `APPROVAL_MANIFEST_SHA256`,
`SERVER_A_MANIFEST_SHA256_VERIFIED`, and `SERVER_B_MANIFEST_SHA256_VERIFIED`.
Normalize CRLF to LF; retain values exactly; sort complete lines by ASCII key; join
with one LF after every line, including the last; then compute lowercase SHA-256.
Blank fields remain present. Markdown prose, fences, headings, signatures, and
section 15 onward are excluded. Implementations must reject duplicate keys.

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

Every gate-status field from `SERVER_A_READY_FOR_CALL` through
`ROLLBACK_AUTHORITIES_AVAILABLE` must equal `PASS`. Separately,
`FINAL_GO_FOR_ONE_CALL_BY` must name the authorized approver and
`FINAL_GO_TIMESTAMP_UTC` must be a valid UTC timestamp within the approved
window. Missing or invalid signoff metadata keeps the call blocked.



## 15. Execution record — the requested seven-step procedure

**This section records work to execute after authorization; every runtime
result is still NOT_RUN. An empty evidence reference is a blocker, not PASS.**

1. **Finalize authorization.** Complete sections 1–14 in the protected copy,
   validate actual signatures and approver authority, and bind the identical
   immutable scope on both hosts. Revalidate the exact destination, caller ID,
   trunk and expiry. A field/date checker cannot verify a signature. No
   placeholder, wildcard, example value or inferred approval is acceptable.
2. **Fresh backups and rollback.** Capture paired Server A database, Odoo
   filestore and configuration backups, and Server B database, VICIdial/Asterisk
   configuration and routing backups, using the approved backup methods. Record
   timestamps, encryption, checksums and off-host copy references. Verify restore
   and rollback against the exact pre-call source/image/configuration tuple.
   Reuse existing approved runbooks; do not guess database names or commands.
3. **Final preflight.** Read back the Odoo company/campaign/list/agent mapping;
   check middleware policy, authorization and idempotency; verify Kong/Caddy
   routes and authentication; independently read back the restricted adapter;
   recheck calling hours, consent and permanent/internal DNC; verify monitoring,
   alert receipt, emergency disable and rollback owners. Bind all readbacks to
   this change and window. UNKNOWN means stop.
4. **Arm only the single approved scope.** Record the actual pre-change flags
   and exact restoration values first. Confirm enforcement of campaign, list,
   agent, extension, destination, caller ID, trunk, deadline, one attempt and one
   concurrent call. A global flag alone does not enforce this scope. If the
   deployed system cannot enforce these bounds, do not arm it. Keep predictive
   and automated dialing, customer lists, callbacks, transfers, SMS and email
   disabled. Keep the pilot hopper empty except for any explicitly approved
   single-call requirement. Establish automatic expiry and an independent
   emergency disable path before temporary enablement.
5. **One manual call.** Only the named operator initiates exactly one call after
   both hosts pass final preflight inside the approved window. No automated
   retry or fallback trunk. A timeout/unknown outcome requires read-only
   reconciliation; it never permits a second attempt under this package.
6. **Full-chain reconciliation.** Obtain authenticated Asterisk/VICIdial call
   identifiers, middleware event and correlation identifiers and the actual
   Odoo call record. Match campaign, list, agent, destination reference,
   disposition, timestamps and terminal outcome across systems. Verify the
   approved recording policy and no duplicate call/lead/CRM event or unrelated
   callback, transfer, SMS or email effects. Test fixture IDs do not count.
7. **Restore fail-closed and decide.** Restore and independently read back all
   temporary flag/resource changes on success, failure or cancellation. Record
   counter deltas, disable time, cleanup and monitoring results. An unanswered
   call or incomplete evidence is not success. The reviewer issues GO/NO-GO for
   the explicitly bounded scope only; a pilot PASS never grants persistent
   production activation or a broader campaign release.

```text
PRE_CALL_BACKUP_GATE=NOT_RUN
BACKUP_CAPTURED_AT_UTC=
SERVER_A_BACKUP_EVIDENCE_REFERENCE=
SERVER_B_BACKUP_EVIDENCE_REFERENCE=
OFF_HOST_BACKUP_EVIDENCE_REFERENCE=
RESTORE_VERIFICATION_REFERENCE=
PRE_CALL_ROLLBACK_GATE=NOT_RUN
EXACT_ROLLBACK_SOURCE_IMAGE_CONFIG_REFERENCE=
ROLLBACK_REHEARSAL_EVIDENCE_REFERENCE=
ODOO_MAPPING_PREFLIGHT=NOT_RUN
MIDDLEWARE_POLICY_IDEMPOTENCY_PREFLIGHT=NOT_RUN
KONG_CADDY_ROUTE_AUTH_PREFLIGHT=NOT_RUN
VICIDIAL_ADAPTER_READBACK_PREFLIGHT=NOT_RUN
CALLING_HOURS_CONSENT_DNC_PREFLIGHT=NOT_RUN
MONITORING_KILL_SWITCH_PREFLIGHT=NOT_RUN
PREFLIGHT_EVIDENCE_REFERENCE=
PRE_CHANGE_FLAGS_EVIDENCE_REFERENCE=
SCOPED_ENFORCEMENT_EVIDENCE_REFERENCE=
AUTO_EXPIRY_EMERGENCY_DISABLE_EVIDENCE_REFERENCE=
SCOPED_ARMING_GATE=NOT_RUN
CALL_EXECUTION_GATE=NOT_RUN
CALL_STARTED_AT_UTC=
CALL_ENDED_AT_UTC=
ASTERISK_UNIQUEID=
ASTERISK_LINKEDID=
VICIDIAL_CALL_ID=
MIDDLEWARE_CORRELATION_ID=
MIDDLEWARE_EVENT_IDS=
ODOO_CALL_MODEL=
ODOO_CALL_RECORD_ID=
FINAL_DISPOSITION=
RECORDING_POLICY_READBACK_REFERENCE=
CALL_CHAIN_RECONCILIATION_GATE=NOT_RUN
AUTHENTICATED_RECONCILIATION_EVIDENCE_REFERENCE=
DUPLICATE_SIDE_EFFECT_CHECK=NOT_RUN
UNRELATED_SIDE_EFFECT_CHECK=NOT_RUN
AUTHORITATIVE_COUNTER_DELTA_REFERENCE=
GLOBAL_CALL_ATTEMPTS=UNKNOWN
CALL_ATTEMPTS_BY_THIS_PREPARATION=0
POST_CALL_FAIL_CLOSED_GATE=NOT_RUN
FLAGS_RESTORED_AT_UTC=
POST_CALL_FLAGS_READBACK_REFERENCE=
POST_CALL_MONITORING_REFERENCE=
BUSINESS_FLOW_CERTIFIED=false
LIMITED_PRODUCTION_DECISION=NO_GO
LIMITED_PRODUCTION_SCOPE_REFERENCE=
FINAL_EVIDENCE_REVIEWER=
FINAL_EVIDENCE_REVIEW_TIMESTAMP_UTC=
PERSISTENT_PRODUCTION_ACTIVATION_AUTHORIZED=false
```

## 16. Retrieval and access results for this preparation

- Exact saved source found: `VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.md`.
  Campaign/list/agent/extension/destination/caller ID/trunk/window and named
  approval fields were empty. The saved package is not signed pilot evidence.
- Repository root lookup of that filename returned 404 at the time checked.
  This preparation adds the sanitized Git copy; it does not overwrite or
  attest to the separate server-local original.
- Connected SentinelX inventory: zero hosts. Neither Server A nor B could be
  selected for live file reads, backups, preflight or calls through that tool.
- The alternative protected GitHub operator workflow requires the current
  protected platform SHA, signed release bundle, approved change and maintenance
  date. Observed branch head: `e44decce67b8bc292753d77a82ca21c9fa37af0f`.
  The lookup of `protected-e44decce67b8bc292753d77a82ca21c9fa37af0f` returned 404.
  No alternate SHA, approval or maintenance date was invented and no protected
  runtime workflow was dispatched.
- No runtime was probed, backed up, armed, called, rolled back or certified by
  this preparation. Existing global flags and call counters remain unobserved.
- The actual business flow remains **BLOCKED / NOT_TESTED**. The missing live
  call IDs cannot be replaced by source tests or a checksummed document.
