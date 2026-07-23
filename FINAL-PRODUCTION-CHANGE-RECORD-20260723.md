# Final production change record — unsigned

Prepared: `2026-07-23`  
Environment: production host `middleware`  
Record status: `BLOCKED_NOT_APPROVED`  
Signature status: `UNSIGNED`

This record documents observed state and the fail-closed governance controls
implemented by commit `93f8c114e810512cf003711587bee0cfce7577b8`. It is not an
approval, activation authorization, risk acceptance, or signature.

## Governance reference register

No authoritative value was found for any required reference below. Values are
deliberately recorded as unassigned rather than inferred from repository
authors, Linux accounts, service identities, or prior test operators.

```text
PRODUCTION_ALERT_RECEIVER=UNASSIGNED
PRIMARY_ESCALATION_OWNER=UNASSIGNED
SECONDARY_ESCALATION_OWNER=UNASSIGNED
RECOVERY_NOTIFICATION_RECEIVER=UNASSIGNED
ALERT_ESCALATION_POLICY_REFERENCE=UNASSIGNED
API_PERMISSION_APPROVER=UNASSIGNED
DNC_POLICY_REFERENCE=UNASSIGNED
DNC_TEST_APPROVER=UNASSIGNED
RECORDING_POLICY_REFERENCE=UNASSIGNED
RECORDING_RETENTION_POLICY=UNASSIGNED
SECURITY_APPROVER=UNASSIGNED
MAINTENANCE_APPROVER=UNASSIGNED
RISK_ACCEPTANCE_OWNER=UNASSIGNED
PRODUCTION_ACTIVATION_APPROVER=UNASSIGNED
FINAL_CHANGE_ID=UNASSIGNED
FINAL_PRODUCTION_WINDOW=UNASSIGNED
ROLLBACK_DECISION_OWNER=UNASSIGNED
```

The deployment script now requires all 17 references in
`/etc/codestra/governance/production.env` and fails with exit status 2 for a
missing, empty, placeholder, unknown, absent, or blocked value.

## Scope and exact source revisions

| Component | Revision |
| --- | --- |
| Governance and monitoring completion | `93f8c114e810512cf003711587bee0cfce7577b8` |
| Middleware | `a4459c26a7de207ec6deaa2d6c3a6871ff1e9cd9` |
| Identity platform | `791b706c0ab3db7cd90c5b2ffd3d10164016127d` |
| n8n workflows | `a0e179391cf4e6b30fdab5195868abdabe80de62` |
| Odoo addons | `e1b8ca76955185b7e9609cf501bfea1dfdeb61e6` |
| VICIdial/Odoo synchronization | `25bae50ee56cfc51ef0d56df50aca9cb0d3b07a6` |

The completion change adds governance validation, protected receiver-file
mounts, primary/secondary/recovery receiver routing, runbook coverage for
every critical alert, and regression tests. It does not deploy the monitoring
stack, activate dialing, enable recording access, change DNC data, provision
VICIdial users, apply migrations, or claim human approval.

## Running image identifiers

```text
middleware=sha256:bded7013b1a5e75b881ffbd8b12cd50428a41f7aec1422761a649a92db80be77
odoo=sha256:9c82d5e40b10228467b6794eea3265e84d66c5a65b57456af54f8e74ef9fac89
n8n=sha256:11524034450080bd0032754892b23ff20be43d72cf320ce75640f7c5475fdca8
redis=sha256:bb186d083732f669da90be8b0f975a37812b15e913465bb14d845db72a4e3e08
postgres=sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94
keycloak=sha256:2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0
reverse_proxy=sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648
```

## Configuration checksums

```text
alertmanager.example.yml=2f99d90cb17e860c7dcfd60c5dc04124e7a40d7f50c243c8633254c47f69e198
compose.monitoring.yaml=e0d08f4f32d113b95f3afc73e95d959f330f551e925359383848ab0492be6695
install-monitoring.sh=3fba777f4dc13c14b245d91fa3dae2ae2585089f9658bdd5a3c1b25d458b2a76
prometheus.yml=ecaff3973a4696904d8617573e49bbcebe6f9ae90c3d947fbe38a443e6b5d0da
platform.rules.yml=28dfd032a5f8b6ba121d5daabce2940055973debe0787434595af70019b6415d
validate-governance.py=80edd54fec71d94225c87bf8ed20fff70c2ac1f8258d0355bab1325408dea244
```

Receiver URLs or tokens are not present in those files. The configuration
references three read-only files beneath `/run/secrets/`; the corresponding
host files must be created beneath `/etc/codestra/secrets/monitoring/` with a
validated restrictive mode only after the receiver references are approved.

## Migration inventory

No migration was applied by this change.

| Migration | SHA-256 |
| --- | --- |
| `0001_integration_outbox.py` | `d7dedefed30609e16778962ad656dc7a2afc45cba9ca56ca1f0b59410f61dfe2` |
| `0002_control_plane.py` | `095b0b735f6d07bfe1d1f0f0d40661decc463d655bd0c44ea25ca58d4dc4069f` |
| `0003_phase1_compat.py` | `745d68b6d8c2771e4a4daf4a11127c60a2be011cb4ce2352b3e58f7980be12e1` |
| `0004_automation_reporting.py` | `a075fb9cde92b7fbbf25260955463221d4b563fcd1d109b5586c873a497cef86` |
| `0005_durable_outbox.py` | `abb716df55437903a5aa76dc7e5c43e2f74159e5632118784407eda5987a6e2e` |
| `0006_lead_reconciliation.py` | `ec0b513fb7615dfcd4f1849219075461ee06b2cc50e44d3044ced694ffddc3ea` |

## Validation results

### Alerting

- Pinned Alertmanager `0.33.1` configuration check: `PASS`, three receivers.
- Pinned Prometheus `3.13.1` config/rule check: `PASS`, 29 rules.
- Critical alert runbook coverage: `PASS`.
- Protected receiver-file enforcement: `PASS`.
- Prior isolated firing and resolved delivery: `PASS`.
- Production firing, acknowledgment, escalation, retry, and resolution:
  `NOT_RUN_BLOCKED`; no validated production receivers or escalation policy.
- Production deployment: `NOT_RUN_FAIL_CLOSED`.
- Secret appearance test for the new configuration and synthetic notification
  projection: `PASS`; production-channel validation remains not run.

### VICIdial API permissions

Observed protected inventory provides one mTLS client identity, not separate
reporting, lead/list, callback/disposition, and controlled-dialing identities.
Runtime safety flags are:

```text
VICIDIAL_READ_ENABLED=false
VICIDIAL_WRITE_ENABLED=false
LIVE_WRITES_ENABLED=false
```

Transport and reliability tests: `PASS_19_OF_19`. Purpose-separated identity
provisioning and positive/negative permission tests:
`NOT_RUN_BLOCKED_NO_IDENTITIES_OR_APPROVER`.

### DNC

The deployed middleware contains limited DNC/transfer denial helpers, but not
an approved, identity-backed DNC policy endpoint supporting the required
allowed/listed/missing-consent/unknown/service-unavailable/token/role/campaign/
replay matrix. Unknown state is therefore prevented from reaching live
dialing by disabled read, write, and live-write flags. The required matrix is
`NOT_RUN_BLOCKED_NO_POLICY_ENDPOINT_IDENTITIES_OR_APPROVERS`.

### Recording

Recording access is default-disabled in the deployed Odoo addon. No approved
recording policy or retention duration was found, and no approved deletion
fixture or designated access identities exist. Enablement, access, retention,
deletion, and metadata behavior validation is
`NOT_RUN_BLOCKED_NO_APPROVED_POLICY`.

## Rollback

Because the monitoring stack was not deployed, production rollback is not
required. Source rollback scope is commit
`93f8c114e810512cf003711587bee0cfce7577b8` only, subject to the named
rollback decision owner's authorization. If a later approved deployment
fails, stop only the `codestra-monitoring` Compose project, preserve its logs
and configuration checksums, restore the last approved Alertmanager
configuration and protected receiver files, and verify existing application
containers remain healthy. Do not enable dialing or recording as a rollback
workaround.

## Approval fields — intentionally unsigned

```text
API_PERMISSION_APPROVER_NAME=
API_PERMISSION_APPROVAL_DATE=
DNC_TEST_APPROVER_NAME=
DNC_TEST_APPROVAL_DATE=
SECURITY_APPROVER_NAME=
SECURITY_APPROVAL_DATE=
MAINTENANCE_APPROVER_NAME=
MAINTENANCE_APPROVAL_DATE=
RISK_ACCEPTANCE_OWNER_NAME=
RISK_ACCEPTANCE_DATE=
PRODUCTION_ACTIVATION_APPROVER_NAME=
PRODUCTION_ACTIVATION_APPROVAL_DATE=
ROLLBACK_DECISION_OWNER_NAME=
ROLLBACK_DECISION_DATE=
SIGNATURES=
```

## Gates

```text
PRODUCTION_ALERT_RECEIVER_GATE=BLOCKED_UNASSIGNED_VALIDATED_RECEIVER
ALERT_ROUTING_GATE=BLOCKED_NOT_DEPLOYED_OR_PRODUCTION_TESTED
ESCALATION_OWNER_GATE=BLOCKED_PRIMARY_SECONDARY_AND_POLICY_UNASSIGNED
API_PERMISSION_GATE=BLOCKED_SEPARATE_IDENTITIES_AND_APPROVER_ABSENT
DNC_POLICY_GATE=BLOCKED_POLICY_ENDPOINT_IDENTITIES_AND_APPROVAL_ABSENT
RECORDING_POLICY_GATE=BLOCKED_POLICY_RETENTION_IDENTITIES_AND_APPROVAL_ABSENT
GOVERNANCE_GATE=BLOCKED_REQUIRED_REFERENCES_AND_APPROVALS_UNASSIGNED
```
