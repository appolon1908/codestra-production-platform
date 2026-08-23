# Server A narrow production operator

Status: reviewed source candidate; root installation is prohibited until the
feature branch is independently approved, merged, and released from the exact
protected commit.

The operator accepts exactly one of `preflight`, `backup`, `validate-backup`,
`restore-test`, `stage`, `canary`, `status`, `rollback`, `collect-evidence`,
`stage-control-plane`, `validate-control-plane`, `activate-control-plane`,
`rollback-control-plane`, `enable-production-web-traffic`, or
`disable-production-web-traffic`.
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
| `codestra-production-operator` | `0d218c880582ac21286b779309b0e7802a50809a6d14f4c3559e1c74ec03edc9` |
| `codestra-production-forced-command` | `bcd05989b44a51828f3b3406e1cd7b9d128a587d68e084a36f2ffbbe26803f3b` |
| `codestra-production-operator.sudoers` | `93e56b18fa54a61192a5a62fe972a74abec37816af8ca977c67cd1bdd75195b9` |
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
start the application API: the container runs a fixed Python sleep command so
artifact identity and hardened container settings can be certified without
requiring production authorization or database configuration. It does not
replace active middleware or alter proxy routing. Backup validation and restore
continue to use the fixed, root-owned `codestra-readiness-backup.service` and
`codestra-readiness-restore.service` units. `validate-backup` invokes only the
fixed root-owned `/opt/codestra/operations/backup/check-backup-state.sh` and
rejects unsafe file type, ownership, mode, or nonzero validation status.

`activate-control-plane` requires exact-tuple PASS evidence from both staging
and validation, a validated encrypted backup, a rollback snapshot, healthy
control-plane services, and exact middleware runtime digests before atomically
committing the active-release pointer. Validation failure invokes the bounded
control-plane rollback. The Web/API traffic actions update only a root-owned
core traffic pointer after validating the active tuple and core dependencies;
they always persist email, SMS, voice, and PSTN as disabled.
