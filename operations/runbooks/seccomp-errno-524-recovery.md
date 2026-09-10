# Server A: seccomp errno 524 recovery

## Scope and incident status

Target: Server A, `65.109.65.169`. Verify its actual hostname and host identity before
running anything. Server B is excluded. This document and the passive collector do
not grant maintenance authorization, install a controller, change a signed release,
or certify production readiness.

Operator-reported observations (not independently read from the host by this patch):

- At `2026-09-07T20:08:29Z`, `bpf_jit_limit=528482304` bytes, about 47 GiB
  MemAvailable, and no matching messages in the inspected kernel logs.
- The built-in Docker seccomp profile is in use. Even `/bin/true` cannot be started
  through `docker exec`; runc reports seccomp filter installation error `errno 524`.
- Backup `20260907T051430Z`: `OBSERVED_PASS`; protected `validate-backup`: `PASS`.
- New protected `restore-test`: `FAIL` before read-only psql can start in the existing
  Keycloak database container. Disposable rehearsal cleanup ran; no deployment followed.
- Failure evidence:
  `/var/lib/codestra-production-operator/evidence/20260907T195622Z-4189612-restore-test.json`.

`HOST_REPAIR=NOT_PERFORMED`; `PRODUCTION_DEPLOYMENT=BLOCKED` until new protected
recovery evidence succeeds. A validated backup is not a validated restore.

## Interpret the error without guessing

In upstream Linux v5.15, `bpf_prog_select_runtime()` returns `-ENOTSUPP` when a BPF
program has not been JIT compiled and JIT compilation is mandatory. Confirm the
running Ubuntu kernel build, configuration, source, and backports before attributing
this host's error to that path. A JIT failure is a candidate, not proof of exhaustion
or a particular kernel defect.

`bpf_jit_limit` is a configured threshold, not a measurement of its current use.
The v5.15 BPF allocator separately charges JIT pages and requests executable memory;
on x86 its module allocator uses a bounded address range. General free RAM and the
absence of visible log messages neither establish nor exclude a JIT allocation
failure. Do not raise a limit merely because an exec failed. Do not declare a kernel/
runtime incompatibility solely from error 524 either.

Read-only process filter-reference counts can double-count shared filters.
`/proc/vmallocinfo` labels provide partial allocation evidence, not exact free
executable space or `bpf_jit_current`. An empty `bpftool prog show` result would not
prove seccomp filter memory is unused; this collector deliberately does not run it.

Primary source references:

- Linux v5.15 BPF runtime selection and allocation:
  https://raw.githubusercontent.com/torvalds/linux/v5.15/kernel/bpf/core.c
- Linux v5.15 x86 module allocation:
  https://raw.githubusercontent.com/torvalds/linux/v5.15/arch/x86/kernel/module.c
- Kernel sysctl reference:
  https://www.kernel.org/doc/html/v5.15/admin-guide/sysctl/net.html
- Kernel seccomp documentation:
  https://www.kernel.org/doc/html/v5.15/userspace-api/seccomp_filter.html
- Docker seccomp guidance:
  https://docs.docker.com/engine/security/seccomp/
- Docker Ubuntu package guidance (do not run installation/removal examples blindly):
  https://docs.docker.com/engine/install/ubuntu/

## Phase 1: passive collection in the existing administrator session

Use the reviewed source in an isolated, unprivileged repository checkout. Do not
replace anything under `/usr/local`, `/etc/codestra`, `/opt/codestra/releases`,
`/run/lock`, sudoers, or the installed protected operator. Review the exact commit and
script before an administrator invokes it. The collector neither invokes sudo nor
opens the Docker socket, so it does not change Model B or grant the operator account
additional rights. Do not repurpose the Keycloak repository runner.

After verifying Server A's identity, run from that checkout:

```bash
python3 tools/diagnose_seccomp_runtime.py \
  --expected-hostname '<verified Server A hostname>' \
  --evidence /var/lib/codestra-production-operator/evidence/20260907T195622Z-4189612-restore-test.json
```

The only placeholder is the actual hostname read back and checked against the
administrator's target inventory; do not use an unverified host's self-report as
independent authorization. Run as the existing authorized administrator only when
needed to read protected evidence. An unprivileged partial result is acceptable;
missing permissions are not permission to weaken the access policy.

The script emits bounded JSON to stdout. Preserve it in an approved private diagnostic
artifact location with mode 0600, not as a substitute protected operator result.
It hashes but does not authenticate the supplied JSON. It emits no raw evidence
payload, process command lines/environments, kernel addresses, APT repository URLs,
or raw journal messages. Review any artifact before committing it.

It reports the kernel/OS, boot ID, uptime, selected kernel flags, BPF sysctls, memory,
partial allocation/process summaries, runtime process executable paths, installed
packages, cached candidate versions, and a summary of the last 500 current-boot
kernel log messages. Collection can be PARTIAL. Exit 0 means collection finished,
not `RESTORE_TEST=PASS`; exit 2 means requested evidence or hostname validation failed.
APT metadata is not refreshed and its candidates are not approved repair versions.
Package metadata does not establish the version of every already-running binary.

For a second observation, collect once again under the same authorization and compare
boot ID, uptime and counters. Do not create repeated failing execs or load test BPF
programs to manufacture a trend. Correlation with uptime is not itself proof of a leak.

## Phase 2: select an evidence-backed repair

An administrator with existing host access must complete the gaps without bypassing
privilege boundaries:

1. Confirm the running Ubuntu ABI and config, installed kernel packages, actual
   Docker/containerd/runc binaries and their package ownership/source. Check whether
   a running executable is marked deleted after an earlier package update. Inspect
   relevant package-change timestamps privately. Do not assume the shell's `runc`
   is the exact executable selected by the daemon.
2. Inspect the relevant kernel/runtime log interval around `2026-09-07T19:56:22Z`
   through `20:08:29Z` privately. The collector's 500-message window may not cover it.
   Separate permission errors, invalid profile errors, allocation failures, and JIT
   failures. Retain the complete original failure evidence privately.
3. Compare exact versions with Ubuntu/Docker primary advisories and package
   changelogs. Another distribution's leak report is not proof of applicability.
   Review Docker CE's bundled `containerd.io` versus Ubuntu's runtime package family;
   do not mix repositories, remove packages, or replace runc ad hoc.
4. If allocator pressure/leak is supported, identify a supported fix to its cause.
   A reboot alone may clear a symptom without fixing recurrence. If a version
   mismatch is supported, select one compatible package set from its existing
   supported source. If neither is supported, retain `ROOT_CAUSE=UNCONFIRMED` and
   escalate the bounded diagnostic evidence to the kernel/runtime maintainer.

No automated repair is embedded in this patch because the exact installed versions,
root cause, target package versions, rollback artifacts, and maintenance window have
not been verified. Do not run `apt upgrade`, purge Docker, alter JIT sysctls, disable
seccomp/AppArmor, add privileged execution, attach live tracing/BPF, use `nsenter`,
or bypass the failed exec using an alternate database path.

## Phase 3: maintenance gate and rollback

Before an upgrade, Docker/containerd restart, workload drain, or reboot, record a
separately approved change binding all of the following:

- Server A identity and exact UTC start/end time, with owner approval.
- Observed package/kernel versions, proposed exact package versions, their source and
  integrity verification, and evidence explaining why they address this failure.
- Impacted workloads and controlled stop/start order; independent console access.
- Backup `20260907T051430Z`, its validation evidence, and the explicitly FAILED
  restore status. Account for newer data and backup freshness; do not pretend the
  recovery risk has disappeared because the dump is present.
- Retained known-good kernel and tested console boot procedure; recoverable runtime
  package/configuration artifacts; explicit rollback triggers and responsible operator.
- Existing external-delivery kill switches, unchanged security policy and unchanged
  Server B. No traffic or application deployment is part of this maintenance.

Package operations may automatically restart services. Treat them as runtime changes,
not harmless preparation. Do not uninstall the running/fallback kernel, change boot
entries without review, or assume Docker live-restore makes maintenance risk-free.
Execute only the authorized plan; no automatic fallback to weakened security.

## Phase 4: prove recovery without changing the goalposts

After the approved repair, with the original/default security policy retained:

1. Read back host identity, boot ID, exact runtime/kernel versions and workload
   identity; record before/after security settings. Through the existing authorized
   administrator path, perform one bounded `/bin/true` exec against the exact
   already-identified Keycloak database container. Do not guess its container name.
   Stop on failure. Do not introduce a new privileged or unconfined probe.
2. Re-run the same protected `validate-backup` and `restore-test` for the selected
   backup/release tuple, using the installed verified operator. Its sequence is the
   authority; do not hand-edit a success marker, checksums, release.json, source locks,
   signatures, or previous evidence. Do not change the restore to avoid its failed
   container operation merely to make a gate pass.
3. Require fresh `OPERATOR_RESULT=PASS`, evidence bound to the exact tuple and backup,
   expected database checks, and verified cleanup of disposable resources. Recheck
   Keycloak/database health, relevant runtime logs, and unchanged external effects.
4. Keep application deployment blocked if any check is unavailable or fails. Even a
   successful recovery test is not blanket authority for a new production deployment.

Required handoff fields:

```text
HOST_IDENTITY=<verified>
KERNEL_BEFORE=<observed>
KERNEL_AFTER=<observed>
RUNTIME_VERSIONS_BEFORE=<observed>
RUNTIME_VERSIONS_AFTER=<observed>
ROOT_CAUSE=<evidence-supported or UNCONFIRMED>
HOST_REPAIR=<performed exact change or NOT_PERFORMED>
SECCOMP_POLICY=<verified unchanged>
DEFAULT_SECCOMP_EXEC=<PASS|FAIL|NOT_RUN>
PROTECTED_VALIDATE_BACKUP=<PASS|FAIL|NOT_RUN>
PROTECTED_RESTORE_TEST=<PASS|FAIL|NOT_RUN>
NEW_EVIDENCE=<actual protected path or NONE>
DISPOSABLE_CLEANUP=<PASS|FAIL|NOT_RUN>
PRODUCTION_DEPLOYMENT=BLOCKED_UNTIL_SEPARATELY_AUTHORIZED
SECURITY_DOWNGRADE=NONE
SERVER_B_CHANGES=NONE
```

## Offline regression tests

```bash
python3 -m unittest discover -s tests -p 'test_diagnose_seccomp_runtime.py' -v
```

These tests exercise parsers, bounded regular-file reads, unsupported-command
rejection, secret minimization, hostname refusal, and unknown/partial states. They
are not host evidence and do not certify Docker or a restore.
