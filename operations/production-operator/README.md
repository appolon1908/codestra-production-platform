# Server A narrow production operator

Status: reviewed source candidate; root installation is prohibited until the
feature branch is independently approved, merged, and released from the exact
protected commit.

The operator accepts exactly one of `preflight`, `backup`, `validate-backup`,
`restore-test`, `stage`, `canary`, `status`, `rollback`, `collect-evidence`,
`kong-readback`,
`stage-control-plane`, `validate-control-plane`, `activate-control-plane`,
`rollback-control-plane`, `enable-production-web-traffic`,
`disable-production-web-traffic`, `enable-klyrow-email-delivery`, or
`disable-klyrow-email-delivery`, plus the bounded `rollout-middleware` and
`rollback-middleware` pair.

Klyrow email enablement requires `/etc/codestra/production-operator/klyrow-email-authorization.json`
as a root-owned `0600` file matching `klyrow-email-authorization.example.json`.
It binds the protected SHA, change ID, and maintenance date to the Klyrow
backup/evidence digest, 14 verified domains, two preserved held messages, a
passing SMTP no-data probe, and passing authorization tests. Exact-tuple
`activate-control-plane` evidence and a validated rollback bundle are also
mandatory. Failed runtime read-back
automatically reapplies the fail-closed override.
There is no shell, Docker-group membership, host/path input, arbitrary unit, or
command argument. `preflight`, `status`, `collect-evidence`, and `kong-readback`
are read-only. `kong-readback` emits only allowlisted route, service, upstream,
target-health, plugin-scope, traffic-gate, and checksum fields. Plugin
configuration, route header matchers, certificates, credentials, and consumer
data are excluded.
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
| `codestra-production-operator` | `54d4b4ba37254910077dfa21292083c69a38af799563277b6052af533a4399d2` |
| `codestra-production-forced-command` | `80ad3377406d35ee0a5c3ecd827c9320a9e03868c8e01a1626faf2920e1bb8fb` |
| `codestra-production-operator.sudoers` | `aebef8205744a176d26334647f52307b7ded040b5170ca2641fc62cb64417b65` |
| `codestra-production-operator.sshd` | `2a6d448ee5abc3cfcd4db5d99392e0459aa7cfec63a6851ccd71c959eb528b6c` |
| `codestra-readiness-restore.override.conf` | `bbc8e4af977ae21b4faffd8c755ed1a0220aebb2796f10c90c94483be3eed06e` |
| `codestra-isolated-restore-rehearsal.sh` | `38cd3df757aec80f01053f431d5b00b31afbad1a0eb4b3a57c7f75df8d1f50c3` |
| `install-server-a-operator.sh` | `PUBLISH_AFTER_PROTECTED_MERGE` |

The installer contains the pinned digests and verifies them before
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
| `/opt/codestra/operations/readiness/codestra-isolated-restore-rehearsal.sh` | `root:root` | `0755` | Exact-backup, exact-image isolated restore and migration gate |
| `/etc/systemd/system/codestra-readiness-restore.service.d/10-protected-operator.conf` | `root:root` | `0644` | Binds the restore unit to the protected rehearsal script |
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
window and when safety flags or telephony counters are unsafe. All four recovery
actions skip remote telephony and runtime-safety probes so an unreachable peer
cannot strand rollback; the recovery operation itself retains its fixed-target,
tuple, checksum, and readback controls. `rollback` can remove
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
`restore-test` requires prior exact-tuple `stage` evidence, selects only the
root-owned backup stamp published in `LAST_SUCCESS`, and publishes its own
atomic `LAST_SUCCESS` marker after checksum validation. The operator validates
that restore result and requires it to bind the same backup stamp, immutable
image digest, Middleware source SHA, schema tables, and Alembic head
`0056_klyrow_delivery_events`. The migration runs as the production migration
identity `middleware_app`, while the runtime remains `mw_integration_api` and its restored grant graph is compared byte for
byte to production, on an internal-only disposable network. The exact candidate
then starts without a host port and must return healthy `/healthz` and
database-online `/readyz` responses before production is touched.

`activate-control-plane` requires exact-tuple PASS evidence from both staging
and validation, a validated encrypted backup, a rollback snapshot, healthy
control-plane services, an exact-tuple Middleware rollout, and exact middleware
runtime digests before atomically committing the active-release pointer.
`rollout-middleware` accepts no path or service argument. It verifies the ten
captured production Compose layers by SHA-256, copies the verified bytes into
an exact-release root-owned directory, and runs Compose only from those copies.
It requires isolated image-stage, protected platform-stage, backup-validation,
and restore-test evidence whose tested backup stamp exactly matches the selected
readiness backup. It migrates through the exact image and recreates only the
integration API, scheduler, and notification worker. A retry preserves the
original exact-tuple rollback marker while that attempt is active. After a
completed rollback, the next attempt verifies the restored runtime and captures
a fresh pre-change database and image snapshot so intervening writes cannot be
lost. Before that snapshot, the operator records and stops the complete,
checksum-pinned Middleware database-client graph, fences new non-superuser
connections, terminates existing sessions, and verifies zero target sessions.
The prior running set remains stopped through migration and replacement, then is
restored exactly after successful readback or rollback. A root-owned `QUIESCED`
marker makes an interruption before bundle publication recoverable without
silently leaving writers stopped. Rollback reads back every restored image
ID and fail-closed environment before recording PASS. The bundle includes the
pre-change Middleware database dump, checksum, owner, Alembic head, and the
validated readiness-backup reference. Rollback stops the three replaced
writers, sets the target database connection limit to zero, terminates every
remaining client session, and only then atomically preserves a checksum-bound
failed-state dump and progress record. It disables all target-database
connections before destructive restore and restores the pre-change database
behind a connection-limit fence. A durable `DATABASE_RESTORED_FENCED` checkpoint
is published immediately after `pg_restore`; only a later
`CONNECTION_POLICY_RESTORED` phase can reopen the captured connection policy.
A retry after `dropdb`, database recreation, `pg_restore`, or connection-policy
restoration resumes from that durable phase without dropping a database that may
have accepted writes or trying to dump a missing database; a completed retry is
read back as an idempotent no-op. Rollback
verifies the prior database head before PASS. The exact-tuple rollback pointer
and phase records are fsynced, atomically replaced, and read back before use.
Both pre-change and failed-state dumps stream directly to protected files and
are incrementally hashed; validation and `pg_restore` also stream from one
verified descriptor, so dump size does not become operator memory use. Every
image record, database dump, checksum, owner/head record, Compose
override, and target manifest is also atomically written and read back; the
bundle directory is fsynced before `LAST_SUCCESS` can advertise it.
It then reads back health, the immutable digest, all delivery-disable flags,
and database head `0056_klyrow_delivery_events`. A failure restores the three
captured image IDs. Control-plane validation failure invokes the bounded
control-plane rollback. The Web/API traffic actions update only a root-owned
core traffic pointer after validating the active tuple and core dependencies;
they always persist email, SMS, voice, and PSTN as disabled.
