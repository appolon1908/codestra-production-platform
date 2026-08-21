# Current protected production activation packet

```text
CHANGE_ID=CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01
PROTECTED_SHA=24c49e08e53d5e3b9894b0b6f959a942533ed276
IMMUTABLE_RELEASE=protected-24c49e08e53d5e3b9894b0b6f959a942533ed276
IMAGE_DIGEST=sha256:336c9a31648a0481737fa4bcc3eafb02a22e4b4fc66ba7b8ec1759c087e05e02
DEPLOYMENT_MANIFEST=deployment-manifest.json
ROLLBACK_MANIFEST=rollback-manifest.json
MAINTENANCE_DATE=UNSET
MAINTENANCE_WINDOW_START=00:00
MAINTENANCE_WINDOW_END=04:00
MAINTENANCE_TIMEZONE=America/New_York
SECURITY_OWNER=Ralph Appolon
PRODUCTION_ACTIVATION_OWNER=Ralph Appolon
MAINTENANCE_APPROVER=Ralph Appolon
ROLLBACK_DECISION_OWNER=Ralph Appolon
ALERT_EMAIL_REFERENCE=CODESTRA_PRODUCTION_ALERT_EMAIL
ALERT_PHONE_REFERENCE=CODESTRA_PRODUCTION_ALERT_PHONE
PRIMARY_ALERT_RECEIVER_REFERENCE=CODESTRA_PRIMARY_ALERT_RECEIVER
RECOVERY_ALERT_RECEIVER_REFERENCE=CODESTRA_RECOVERY_ALERT_RECEIVER
ESCALATION_POLICY_REFERENCE=CODESTRA_ALERT_ESCALATION_POLICY
API_PERMISSION_POLICY=docs/production/API_PERMISSION_POLICY.md
DNC_POLICY=docs/production/DNC_POLICY.md
RECORDING_POLICY=docs/production/RECORDING_POLICY.md
BACKUP_REFERENCE=PENDING_FRESH_MAINTENANCE_BACKUP
RESTORE_TEST_REFERENCE=PENDING_ISOLATED_RESTORE
PREFLIGHT_EVIDENCE_REFERENCE=PENDING
ROLLBACK_REHEARSAL_REFERENCE=PENDING
SIGNATURE_STATUS=PENDING
ACTIVATION_AUTHORIZATION=PENDING_PROTECTED_APPROVAL
```

## Canary and soak

The canary is loopback/private, synthetic, no-external-side-effect, and bounded
to one application transaction per required flow. PSTN, callbacks, customer
messaging, and real payments remain disabled. Acceptance requires a one-hour
monitored soak followed by a one-business-day monitored soak.

## Rollback triggers

Rollback is immediate for an identity, digest, signature, attestation,
migration, backup, restore, health, authorization, data-integrity, queue,
monitoring, provider, disk, side-effect, or kill-switch failure.

## Approval intent (not a signature)

```text
API_PERMISSION_APPROVER_NAME=Ralph Appolon
API_PERMISSION_DECISION=YES
DNC_POLICY_APPROVER_NAME=Ralph Appolon
DNC_POLICY_DECISION=YES
RECORDING_POLICY_APPROVER_NAME=Ralph Appolon
RECORDING_POLICY_DECISION=YES
SECURITY_APPROVER_NAME=Ralph Appolon
PRODUCTION_ACTIVATION_APPROVER_NAME=Ralph Appolon
ROLLBACK_DECISION_OWNER_NAME=Ralph Appolon
SIGNATURE_STATUS=PENDING
ACTIVATION_AUTHORIZATION=PENDING_PROTECTED_APPROVAL
```

GitHub protected review and production-environment approval must record the
reviewer identity and timestamps. This packet must not be edited to claim those
events before GitHub records them.
