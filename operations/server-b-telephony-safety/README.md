# Server B telephony safety operator

This source defines only the forced-command compatibility boundary required by
the unchanged Server A production operator. It accepts the two exact original
SSH command strings for Asterisk channel and PJSIP-registration counts. It does
not expose raw Asterisk sudo, a shell, lifecycle actions, backup/restore actions,
or legacy delegation.

The forced command must be installed through the exact `authorized_keys.template`
options. Replace only `SSH_PUBLIC_KEY_PLACEHOLDER` through an independently
reviewed provisioning process; never commit key material.

`install.sh <protected-commit>` refuses dirty source, a revision other than HEAD,
or a revision not contained in `origin/release/production-activation`. It creates
a root-only, randomized and checksummed backup before atomically replacing files
and installs `REVISION` and `SHA256SUMS` read-backs under
`/etc/codestra/server-b-telephony-safety`. An exclusive root lock under the
persistent project-local `/root/vicidial-sync-remediation/.locks` root serializes
the entire backup/staging/install transaction and remains available after reboot.
Neither installer nor rollback modifies `/run/lock`. Rollback rejects unsealed, altered,
misowned, or legacy timestamp-only backup directories.

The installer does not edit `authorized_keys` and does not reload SSH. After an
administrator installs the separately reviewed authorized-key entry, validate
with `visudo -cf /etc/sudoers` and `sshd -t` before a reload. The historical
14-action operator and its `restore-test` are not approved by this package.
