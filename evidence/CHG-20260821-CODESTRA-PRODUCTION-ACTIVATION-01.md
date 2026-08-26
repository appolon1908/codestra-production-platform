# Current protected production activation packet

```text
CHANGE_ID=CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01
PROTECTED_SHA=BOUND_BY_PROTECTED_RELEASE_AFTER_MERGE
IMMUTABLE_RELEASE=BOUND_BY_PROTECTED_RELEASE_AFTER_MERGE
MIDDLEWARE_SOURCE_SHA=35448ef85ae56db3651a72b61db8e242b7aacd2e
IMAGE_DIGEST=sha256:09d4bd0f7b2376e0a06d3efae27a6642429389fa7e3277791ec0b36584e87175
MIDDLEWARE_RELEASE_RUN=32612498385
MIDDLEWARE_RELEASE_ARTIFACT=exact-main-production-35448ef85ae56db3651a72b61db8e242b7aacd2e-32612498385-1
MIDDLEWARE_SBOM_SHA256=cc1eee1c253ad84be81c8fdccbdfe1fb35b146244256a66b3e7ec0c6aebb2433
MIDDLEWARE_PROVENANCE_SHA256=da9c7aef9c2ce6e7fe5c1455cbee9a1c052faf0ac62e80a77d35b4196e525537
MIDDLEWARE_OPENVEX_SHA256=49939dbe8783bc12e226d851cfd1ddece4af4c6f28b6ffa5c2ef54f5daca46b7
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

The former active target `sha256:f48206bbcbff7ad791de32a1026a95856489e6ee054ff13779facbf30ee8c28a`
is superseded and denied for every new activation. It is retained only as
historical/rollback evidence subject to schema-compatibility certification.

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
