# Codestra provider-host audit authority

This package installs one additive Linux Audit rule file on the Codestra
provider/communications host. It does not install operating-system packages,
change SSH configuration, touch containers, or change application state.

The rule set records:

- changes to SSH, sudo, audit, Codestra operator, and `codestra-admin` key
  authority paths;
- root-session and non-root-to-root command execution; and
- changes to root-owned Codestra validation state.

It deliberately contains no `-D` rule flush and no `-e 2` kernel lock. Existing
rules remain in force, and an immutable kernel audit configuration is never
silently weakened or replaced. The installer fails before mutation when the
kernel is already locked and the exact rule set is not already active.

## Prerequisites

- Debian or Ubuntu with the distribution `auditd` package already installed;
- an authorized, audited installation administrator with root privilege;
- the exact protected platform archive, deployment manifest, checksum manifest,
  and detached signature;
- a root-owned allowed-signers authority obtained independently of that release,
  plus its approved SHA-256 key fingerprint; and
- existing `/opt/codestra`, `/var/lib/codestra`, and `codestra-admin` SSH
  authority paths.

Package installation is intentionally outside this script because an unpinned
network package transaction is not an acceptable side effect of a host-security
change.

## Install

Run the installer extracted from the exact protected release archive. The
allowed-signers path is a separately provisioned trust authority; it must not
come from the release being verified.

```text
python3 -I operations/host-auditd/install-provider-host-auditd.py install \
  --source-sha <40-hex-protected-sha> \
  --release-archive <codestra-production-platform-SHA.tar.gz> \
  --release-manifest <deployment-manifest.json> \
  --release-checksums <manifest.sha256> \
  --release-signature <manifest.sha256.sig> \
  --allowed-signers </independent/root-owned/allowed_signers> \
  --expected-signer-fingerprint <SHA256:fingerprint> \
  --change-id <approved-change-id> \
  --approver <named-approver>
```

Before any host-state mutation, the installer snapshots every release input
once into private root-owned staging, verifies the approved signer fingerprint
and OpenSSH signature in the `codestra-release` namespace, binds the archive and
manifest to the exact protected SHA, and requires its own bytes to match the
installer in that signed archive. The managed rule and validator are read only
from that archive. It then snapshots the prior managed rule, generated aggregate
rules, service state, and checksums; writes atomically; enables/starts `auditd`
without restarting it; validates the exact live state; and durably records the
release identity and installation evidence. Repeating the exact signed install
is idempotent.

## Validate

```text
python3 -I /usr/local/sbin/validate-codestra-provider-host-auditd \
  --expected-source-sha <40-hex-protected-sha>
```

Validation requires an enabled and active daemon, kernel auditing enabled,
zero lost records, all managed keys active, protected root-owned files, and a
bounded synthetic audit record that is read back from the audit log. PASS is
printed only after root-owned evidence is completely written and synced.

## Roll back the managed rule

Rollback restores only the managed files captured by the requested checkpoint
and the prior enable/active state:

```text
python3 -I operations/host-auditd/install-provider-host-auditd.py rollback \
  --backup-stamp <UTC-checkpoint> \
  --expected-source-sha <40-hex-protected-sha>
```

Do not use rollback to disable a production-certified audit service merely to
complete a test. Operator, application, Docker, firewall, DNS, and delivery
configuration are outside this package's mutation boundary.
