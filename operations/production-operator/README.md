# Server A narrow production operator

Status: reviewed source candidate; root installation is prohibited until the
feature branch is independently approved, merged, and released from the exact
protected commit.

The operator accepts exactly one of `preflight`, `backup`, `validate-backup`,
`restore-test`, `stage`, `canary`, `status`, `rollback`, or `collect-evidence`.
There is no shell, Docker-group membership, host/path input, arbitrary unit, or
command argument. `preflight`, `status`, and `collect-evidence` are read-only.
Every other action requires `/etc/codestra/production-operator/maintenance-date`
to be a root-owned regular file with mode `0600`, containing one `YYYY-MM-DD`
date, and the current time must be 00:00 through 03:59 America/New_York.

## Reviewed artifacts

| Repository artifact | SHA-256 |
|---|---|
| `codestra-production-operator` | `7eb6e80b233fce31fe34404a31a82a9fa6d0afd076b6b67a9938c4806999d015` |
| `codestra-production-forced-command` | `9bc6974aa56ee015de6a03db754fed3594e85d381bc9c98b405d10894cea6b95` |
| `codestra-production-operator.sudoers` | `593cdff802459d3e9ce0d9c9afc17c330df15f4753521c6ad7f2a6c6790a632d` |
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
| `/etc/codestra/production-operator` | `root:root` | `0700` | Operator configuration |
| `/etc/codestra/production-operator/maintenance-date` | `root:root` | `0600` | Supplied separately after approval |
| `/etc/codestra/production-operator/installed.sha256` | `root:root` | `0600` | Installed-file checksum manifest |
| `/var/lib/codestra-production-operator` | `root:root` | `0700` | Evidence and rollback root |
| `/var/lib/codestra-production-operator/.ssh` | operator user/group | `0700` | SSH key directory |
| `/var/lib/codestra-production-operator/.ssh/authorized_keys` | operator user/group | `0600` | One caller-supplied ED25519 key with forced command |
| `/var/lib/codestra-production-operator/evidence` | `root:root` | `0700` | Sanitized per-action evidence |

The system user is password-locked. SSH requires public-key authentication,
has no TTY or forwarding, and applies the forced command in both `sshd_config`
and `authorized_keys`. Sudoers enumerates nine exact command lines and contains
neither `NOPASSWD: ALL` nor wildcard arguments.

## Installation and validation

After protected merge, use the published installer digest and a standalone
ED25519 public-key file. Never paste the installer or key into a quoted shell
command.

```sh
sha256sum --check install-server-a-operator.sh.sha256
sudo ./install-server-a-operator.sh /path/to/operator-ed25519.pub
sudo ./validate-server-a-operator.sh
```

The installer backs up every replaced target into a mode-0700 root directory.
Any installation failure restores the prior files. It rejects symlink targets,
modified payloads, unsafe source/key modes, unexpected ownership or modes on
existing targets, malformed or multiple keys, invalid sudoers, and invalid SSH
configuration.

## Status and operation

Remote callers send one literal action, for example `status`. Extra arguments,
paths, metacharacters, empty commands, subsystems, port forwarding, and
interactive sessions are rejected. Each accepted invocation acquires a global
lock and writes a sanitized JSON result under the evidence directory.

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
