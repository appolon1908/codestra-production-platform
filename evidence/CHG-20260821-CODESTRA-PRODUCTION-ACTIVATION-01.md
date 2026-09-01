# Current protected production activation packet

```text
CHANGE_ID=CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01
PROTECTED_SHA=BOUND_BY_PROTECTED_RELEASE_AFTER_MERGE
IMMUTABLE_RELEASE=BOUND_BY_PROTECTED_RELEASE_AFTER_MERGE
MIDDLEWARE_SOURCE_SHA=f199b6c40f4e467979e9a8b255a0e686321a182d
IMAGE_DIGEST=sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b
MIDDLEWARE_RELEASE_RUN=32919188388
MIDDLEWARE_RELEASE_ARTIFACT=exact-main-production-f199b6c40f4e467979e9a8b255a0e686321a182d-32919188388-1
MIDDLEWARE_SBOM_SHA256=c4204cc274578cf282736c7ad440d36d6aa8b8f499bf6595665ba4356e7fefe8
MIDDLEWARE_PROVENANCE_SHA256=2d429d6689dbd6b53d1201dd561c1fe31ccc60902578a8b90638e20d28f8a262
MIDDLEWARE_OPENVEX_SHA256=1775dab6f324719b6ab5ea2abd4aa9ec017570702026c952017ba85e96c4c270
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

The prior protected target
`sha256:09d4bd0f7b2376e0a06d3efae27a6642429389fa7e3277791ec0b36584e87175`
at source `35448ef85ae56db3651a72b61db8e242b7aacd2e` is retained only as the
captured rollback image for this change. It is not an allowed new activation
target. The still older target
`sha256:f48206bbcbff7ad791de32a1026a95856489e6ee054ff13779facbf30ee8c28a`
remains superseded and denied.

## Required activation order

`preflight` → `backup` → `validate-backup` → `stage` → `restore-test` →
`stage-control-plane` → `validate-control-plane` → `rollout-middleware` →
`activate-control-plane` → `status` → `collect-evidence`.

`rollout-middleware` is bounded to the integration API, scheduler, and
notification worker. It requires exact-tuple backup/restore evidence whose
tested backup stamp equals the currently selected backup, isolated image stage,
exact-image isolated migration/readback through `0056_klyrow_delivery_events`,
and protected platform-stage evidence, then migrates production to
`0056_klyrow_delivery_events`, reads back the exact digest and schema head, and
automatically calls `rollback-middleware` if the
rollout or readback fails. No retained Klyrow event is replayed until a new
synthetic event and its exact replay produce one durable inbox row and the
approved Odoo readback succeeds.

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
