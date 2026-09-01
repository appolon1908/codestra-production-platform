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
- the exact signed protected platform source archive; and
- existing `/opt/codestra`, `/var/lib/codestra`, and `codestra-admin` SSH
  authority paths.

Package installation is intentionally outside this script because an unpinned
network package transaction is not an acceptable side effect of a host-security
change.

## Install

From the exact protected source tree, run:

```text
python3 -I operations/host-auditd/install-provider-host-auditd.py install \
  --source-sha <40-hex-protected-sha> \
  --change-id <approved-change-id> \
  --approver <named-approver>
```

The installer snapshots the prior managed rule, generated aggregate rules,
service state, and checksums before mutation. It writes the managed rule
atomically, enables/starts `auditd` without restarting it, loads the aggregate
rules, validates the exact live state, then durably records installation
evidence. Repeating the exact install is idempotent.

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

Rollback restores only the two files captured by the requested checkpoint and
the prior enable/active state:

```text
python3 -I operations/host-auditd/install-provider-host-auditd.py rollback \
  --backup-stamp <UTC-checkpoint> \
  --expected-source-sha <40-hex-protected-sha>
```

Do not use rollback to disable a production-certified audit service merely to
complete a test. Operator, application, Docker, firewall, DNS, and delivery
configuration are outside this package's mutation boundary.
