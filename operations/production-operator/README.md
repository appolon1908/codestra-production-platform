# Server A narrow production operator

Status: reviewed source candidate; root installation is prohibited until the
feature branch is independently approved, merged, and released from the exact
protected commit.

The operator accepts exactly one of `preflight`, `backup`, `validate-backup`,
`restore-test`, `stage`, `canary`, `status`, `rollback`, `collect-evidence`,
`stage-control-plane`, `validate-control-plane`, `activate-control-plane`,
`rollback-control-plane`, `enable-production-web-traffic`, or
`disable-production-web-traffic`, plus the bounded `rollout-middleware` and
`rollback-middleware` pair.
There is no shell, Docker-group membership, host/path input, arbitrary unit, or
command argument. `preflight`, `status`, and `collect-evidence` are read-only.
Every other action except emergency `rollback` requires
`/etc/codestra/production-operator/maintenance-date`

Outside that window, mutation is allowed only when the fixed evidence files
`/opt/codestra/evidence/production-readiness-soak/20260822T022734Z/OWNER-MAINTENANCE-WINDOW-WAIVER.txt`
and its `.sha256` manifest are regular root-owned mode `0600` files, the
checksum is exact, and all four owner authorization statements are present.
The evidence path is compiled into the operator and cannot be supplied through
arguments or environment variables. This waiver changes only the time-window
decision; the installed release tuple, protected environment, runtime safety,
and action restrictions remain mandatory.
to be a root-owned regular file with mode `0600`, containing one `YYYY-MM-DD`
date, and the current time must be 00:00 through 03:59 America/New_York.

## Reviewed artifacts

| Repository artifact | SHA-256 |
|---|---|
| `codestra-production-operator` | `c90b3e1b7a07e7ca5a2d8d7a55a0eb3e327c4f9501c4efa0d17bb5be3365ce41` |
| `codestra-production-forced-command` | `d806b91ae6d9ddf962883487ffebaf3ac503ed3ef79b0d9a9bdedc222e64cf8c` |
| `codestra-production-operator.sudoers` | `9023d679f923587eaaed3d0c27b5c388a136d112a9483777881b5aea002ed520` |
| `codestra-production-operator.sshd` | `2a6d448ee5abc3cfcd4db5d99392e0459aa7cfec63a6851ccd71c959eb528b6c` |
| `install-server-a-operator.sh` | `PUBLISH_AFTER_PROTECTED_MERGE` |

The installer contains the first four pinned digests and verifies them before
writing host files. The installer digest is published only after protected
merge so it describes the immutable reviewed artifact rather than a draft.

## Installed inventory

| Path | Owner | Mode | Purpose/checksum |
|---|---|---:|---|
| `/usr/local/sbin/codestra-production-operator` | `root:root` | `0750` | Pinned above |
| `/usr/local/libexec/codestra-production-forced-command` | `root:root` | `0755` | Pinned above |
| `/etc/sudoers.d/codestra-production-operator` | `root:root` | `0440` | Pinned; validated by `visudo -cf` |
| `/etc/ssh/sshd_config.d/60-codestra-production-operator.conf` | `root:root` | `0644` | Pinned; validated by `sshd -t` |
| `/etc/codestra/production-operator` | `root:root` | `0755` | Non-secret tuple directory; protected files retain restrictive modes |
| `/etc/codestra/production-operator/maintenance-date` | `root:root` | `0600` | Installed from the approved tuple |
| `/etc/codestra/production-operator/release.json` | `root:root` | `0644` | Immutable release tuple used by the forced command |
| `/etc/codestra/production-operator/control-plane-archive.sha256` | `root:root` | `0644` | Exact protected control-plane archive digest |
| `/etc/codestra/production-operator/installed.sha256` | `root:root` | `0600` | Installed-file checksum manifest |
| `/var/lib/codestra-production-operator` | `root:codestra-production-operator` | `0710` | Traversable operator home; contents remain non-listable and individually restricted |
| `/var/lib/codestra-production-operator/.ssh` | operator user/group | `0700` | SSH key directory |
| `/var/lib/codestra-production-operator/.ssh/authorized_keys` | operator user/group | `0600` | One caller-supplied ED25519 key with forced command |
| `/var/lib/codestra-production-operator/evidence` | `root:root` | `0700` | Sanitized per-action evidence |

The system user is password-locked. SSH requires public-key authentication,
has no TTY or forwarding, and applies the forced command in both `sshd_config`
and `authorized_keys`. The validator switches to the dedicated account to prove
that the complete parent-directory chain permits reading that key. Sudoers
enumerates nine exact command lines and contains
neither `NOPASSWD: ALL` nor wildcard arguments.

## Installation and validation

After protected merge, use the published installer digest and a standalone
ED25519 public-key file. Never paste the installer or key into a quoted shell
command.

```sh
sha256sum --check install-server-a-operator.sh.sha256
sudo ./install-server-a-operator.sh /path/to/operator-ed25519.pub PROTECTED_SHA IMAGE_DIGEST CHANGE_ID MAINTENANCE_DATE CONTROL_PLANE_ARCHIVE_SHA256
sudo ./validate-server-a-operator.sh
```

The installer backs up every replaced target into a mode-0700 root directory.
Any installation failure restores the prior files. It rejects symlink targets,
modified payloads, unsafe source/key modes, unexpected ownership or modes on
existing targets, malformed or multiple keys, invalid sudoers, and invalid SSH
configuration.

## Status and operation

Remote callers send an action plus the exact installed SHA, image digest,
change ID, and maintenance date. Tuple mismatches, extra arguments, paths,
metacharacters, empty commands, subsystems, port forwarding, and interactive
sessions are rejected before sudo. Each accepted invocation acquires a global
lock and writes a sanitized JSON result under the evidence directory.
`status` and `collect-evidence` remain available when a safety probe fails so
an incident can be diagnosed. `rollback` remains available outside the normal
window and when safety flags or telephony counters are unsafe; it can remove
only the fixed standby container when its digest matches the installed tuple.
All pre-activation actions require exact zero
calls/channels, no SIP registrations, and the complete canonical release flag
set with every value exactly `false`.

## Removal and rollback

Run the reviewed removal file locally as root with no arguments:

```sh
sudo ./remove-server-a-operator.sh
```

It creates a root-only tar archive and checksum under
`/var/lib/codestra-production-operator/removal`, removes authorization before
the executable, locks the service account, and validates the remaining SSH and
sudo configuration. Restore a prior installer backup only during an approved
maintenance window, then rerun `validate-server-a-operator.sh`.

Installation does not enable PSTN dialing, external delivery, customer
communications, callbacks, or payments. Missing fixed systemd operation units,
failed safety checks, non-zero calls/channels, or missing privileged telephony
readback make operations fail closed.

`stage` accepts the GHCR read credential only on standard input, pulls and
verifies the installed immutable digest, and creates only the fixed standby
container with network mode `none`, a read-only root filesystem, all
capabilities dropped, and production-delivery flags disabled. It does not
start the application API: the container runs a fixed inert Python wait so
artifact identity and hardened container settings can be certified without
requiring production authorization or database configuration. A stale stopped
container for the same digest is recreated only when its configuration differs,
so staging is idempotent across operator upgrades and delayed approvals. It does not
replace active middleware or alter proxy routing. Backup validation and restore
continue to use the fixed, root-owned `codestra-readiness-backup.service` and
`codestra-readiness-restore.service` units. `validate-backup` invokes only the
fixed root-owned `/opt/codestra/operations/backup/check-backup-state.sh` and
rejects unsafe file type, ownership, mode, or nonzero validation status.

`activate-control-plane` requires exact-tuple PASS evidence from both staging
and validation, a validated encrypted backup, a rollback snapshot, healthy
control-plane services, an exact-tuple Middleware rollout, and exact middleware
runtime digests before atomically committing the active-release pointer.
`rollout-middleware` accepts no path or service argument. It verifies the ten
captured production Compose layers by SHA-256, copies the verified bytes into
an exact-release root-owned directory, and runs Compose only from those copies.
It requires isolated image-stage, protected platform-stage, backup-validation,
and restore-test evidence, migrates through the exact image, and recreates only
the integration API, scheduler, and notification worker. A retry preserves the
original exact-tuple rollback marker; rollback reads back every restored image
ID and fail-closed environment before recording PASS. The bundle includes the
pre-change Middleware database dump, checksum, owner, Alembic head, and the
validated readiness-backup reference. Rollback stops the three writers,
atomically preserves a checksum-bound failed-state dump and progress record,
then restores the pre-change database. A retry after `dropdb`, `createdb`, or
`pg_restore` resumes from that durable record without trying to dump a missing
database; a completed retry is read back as an idempotent no-op. Rollback
verifies the prior database head before PASS. The exact-tuple rollback pointer
and phase records are fsynced, atomically replaced, and read back before use.
It then reads back health, the immutable digest, all delivery-disable flags,
and database head `0056_klyrow_delivery_events`. A failure restores the three
captured image IDs. Control-plane validation failure invokes the bounded
control-plane rollback. The Web/API traffic actions update only a root-owned
core traffic pointer after validating the active tuple and core dependencies;
they always persist email, SMS, voice, and PSTN as disabled.
