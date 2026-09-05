# Server A governed email readiness evidence — 2026-09-05

## Decision

`BLOCKED` and fail closed. No production configuration, workload, database,
operator, SSH, resolver, SMTP, or delivery state was changed. No email canary was
sent.

The trust-anchor gate was repeated after the operator requested continuation.
`/etc/codestra/release/allowed_signers` remained absent, and no independent
release-signer fingerprint record was found in the authorized host locations
inspected. The release signature therefore remains unverified.

During the repeated disabled-state check, two sensitive runtime environment
values were inadvertently rendered in the authorized root-session output by a
filter-boundary error. The values are not reproduced in this evidence. They
must be treated as exposed session data and rotated through the governed secret
rotation procedure before readiness can be claimed. No runtime configuration
was changed during the check.

The release archive checksum is exact, and GitHub identifies the immutable
release tag with target commit
`01f2676772b11919e1d79cc74d36bc5eeaa682cd`. Installation stopped before
archive extraction because Server A does not have the independently
provisioned SSH release-signing trust anchor required by
`docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md` at
`/etc/codestra/release/allowed_signers`.

The only other signing public keys located on the host are PEM application
authorization keys. They are not OpenSSH release-signing keys and were not
substituted for the missing trust anchor.

## Sanitized observations

- Observation time: `2026-09-05T12:53:42Z` through `2026-09-05T12:56:08Z`
- Hostname: `middleware`
- Effective user: `root` (`uid=0`)
- Public address: `65.109.65.169`
- Operating system: Ubuntu 22.04 LTS
- Requested release tag:
  `protected-01f2676772b11919e1d79cc74d36bc5eeaa682cd`
- Requested archive SHA-256:
  `9a8ca7da2c9a7c7b44fa2bd53888b5353326a24965edfdd824a90eaa4068ff1b`
- Downloaded archive SHA-256: exact match
- `sha256sum --check --strict manifest.sha256`: all listed assets passed
- Manifest SSH signature: not verified; required host trust anchor absent
- Installed protected SHA: `278c115b8f9c0f8a34be285ee26b095c094d8186`
- Requested protected SHA: `01f2676772b11919e1d79cc74d36bc5eeaa682cd`
- Requested Middleware digest:
  `sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b`
- Requested migration head: `0056_klyrow_delivery_events`
- Change ID: `CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01`
- Delivery read-back: `KLYROW_MODE=test`; live email and SMS flags are false
  on the relevant control-plane and Middleware workloads.
- Direct Odoo SMTP was not configured.
- Protected preflight run:
  <https://github.com/appolon1908-hue/codestra-production-platform/actions/runs/33966259819>
  — `verify=success`, `approved-operation=failure`, overall `failure`.
- Existing resolver result carried into this run: `503
  core_web_api_maintenance`. No resolver exemption was applied because the
  release signature gate did not pass.

## Installed operator integrity read-back

| Object | Owner/mode | SHA-256 |
| --- | --- | --- |
| `/usr/local/sbin/codestra-production-operator` | `root:root 0750` | `717669c7ddca3254fa9fbd42048a608034f1e947d3e20abc8a7f66471678923a` |
| `/usr/local/libexec/codestra-production-forced-command` | `root:root 0755` | `bcd05989b44a51828f3b3406e1cd7b9d128a587d68e084a36f2ffbbe26803f3b` |
| `/etc/sudoers.d/codestra-production-operator` | `root:root 0440` | `93e56b18fa54a61192a5a62fe972a74abec37816af8ca977c67cd1bdd75195b9` |
| `/etc/ssh/sshd_config.d/60-codestra-production-operator.conf` | `root:root 0644` | `2a6d448ee5abc3cfcd4db5d99392e0459aa7cfec63a6851ccd71c959eb528b6c` |
| `/etc/codestra/production-operator/release.json` | `root:root 0644` | `83eb5a11036529f130f1b75700a9bf4dbe1e0abb88bc7a797108587590d1d524` |

## Runtime digest mismatches relevant to the gate

The requested Middleware digest was not observed in the relevant running
workloads. Selected immutable runtime read-backs included:

- Appolon integration API:
  `sha256:695fa3ce3f50ba4d0ae0784976b946a0a683ca731155e4bd3bd9e90a4670b820`
- Notification worker:
  `sha256:73fe86858d7a9303bbb151c77097aa43c0739e71c4781636e7db81dd4eadbf98`
- Reconciliation worker:
  `sha256:1a9e13a0c930d36076b5742e17f948dc85d9bc6ace90e58052756c8b1ad42700`

These were inventory observations only. No workload authority or database
lineage was replaced.

## Required unblock

A security owner must deliver the approved SSH signing public key and its
64-hex SHA-256 fingerprint through independent protected channels. An
authorized administrator can then use the release's documented
`tools/provision_release_trust_anchor.py` procedure to provision
`/etc/codestra/release/allowed_signers`. The fingerprint must not be derived
from the release being authenticated.

After that independent gate is satisfied, the mission must restart at
signature verification. Backups, installer inspection, operator installation,
resolver repair, database checks, SMTP no-DATA tests, activation, and canary
work have not run and must not be represented as passed. The cited protected
preflight did run: its verification job succeeded, its approved-operation job
failed, and the overall run failed.

## Final state

```text
SERVER_A_OPERATOR_INSTALL=FAIL
PROTECTED_SHA_READBACK=278c115b8f9c0f8a34be285ee26b095c094d8186
MIDDLEWARE_DIGEST_READBACK=NOT_MATCHED
CHANGE_ID_READBACK=CHG-20260821-CODESTRA-PRODUCTION-ACTIVATION-01
BACKUP_VERIFIED=NOT_RUN
ROLLBACK_READY=NOT_RUN
RESOLVER_AUTHORIZATION=BLOCKED
RESOLVER_NEGATIVE_TESTS=NOT_RUN
MIGRATION_HEAD=NOT_VERIFIED
SMTP_STARTTLS=NOT_RUN
SMTP_NO_DATA=NOT_RUN
UNAUTHORIZED_RELAY_DENIED=NOT_RUN
QUEUE_DELTA=NOT_MEASURED
PROTECTED_PREFLIGHT=https://github.com/appolon1908-hue/codestra-production-platform/actions/runs/33966259819 failure
EMAIL_DELIVERY_ENABLED=NO
SMS_DELIVERY_ENABLED=NO
PSTN_DELIVERY_ENABLED=NO
CANARY_SENT=NO
CANARY_RECIPIENT=NOT_AUTHORIZED
CANARY_DELIVERY=NOT_RUN
ROLLBACK_TEST=NOT_RUN
PRODUCTION_CHANGED=NO
FINAL_STATUS=BLOCKED
BLOCKERS=Missing independently provisioned SSH release-signing trust anchor and fingerprint; two runtime secrets require governed rotation after session-output exposure; installed operator tuple is older; requested Middleware digest is not running; resolver remains 503; downstream gates were not run
PR_URLS=https://github.com/appolon1908-hue/codestra-production-platform/pull/274
EVIDENCE_PATH=evidence/server65/GOVERNED-EMAIL-READINESS-20260905.md
```
