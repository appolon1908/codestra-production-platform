# Server B SentinelX installation review

Status: **BLOCKED_ROOT_ACCESS**. Independently, the reviewed agent does not
provide the requested script/upload policy controls. Do not run the installer
or enroll using this candidate alone. No installation was attempted.

## Scope and administrative prerequisite

Only SentinelX installation and restricted host inspection are authorized.
Ralph creation, business writes, calls, telephony activation, service restarts
outside SentinelX, firewall changes and SSH changes are out of scope.

The session is on `static`, public `65.21.67.207`, private `10.40.0.2`,
openSUSE Leap 15.6 x86_64. Effective identity is `codestra-admin` (UID/GID 1001).
`sudo -n -l` shows general access cancelled by `(ALL) !ALL`, with only enumerated
`codestra-vicidial-operator` operations allowed without a password. None is a
SentinelX installation path. No bypass, permission modification, credential
search, root SSH attempt, or use of an operator mutation was performed.

The exact privileged step still required is an existing authorized root
console/session on this host, to inspect protected grants and installation
state, stage reviewed artifacts in `/root/sentinelx-install`, and provision
root-owned policy and service confinement before any enrollment/connection.
Do not give `codestra-admin` extra sudo rights for this task.

## Download and source review

Review artifacts are retained privately at
`/home/codestra-admin/artifacts/sentinelx-install-review-20260905` (0700).
The installer was downloaded with HTTPS-only curl and TLS >=1.2, never executed.
`bash -n` passed. SHA256 is evidence of downloaded bytes, not publisher
authentication. Exact hashes and source commits are in `evidence.json`.

Sources:

- https://get.sentinelx.app/install.sh
- https://github.com/pensados/sentinelx-cloud-installer/tree/e637b12c35e40a81fef3171394fe863235575dfb
- https://github.com/pensados/sentinelx-cloud-core/tree/d6b33822b61e7fccf39547d5cce8add8bc7021f9

The download differs from the installer repository version: its missing-example
fallback contains a large starter policy/playbook heredoc where repository main
instead fails. Never silently substitute either version or use the broad fallback.
The separately downloaded enrollment helper matches the reviewed repository helper.

Installer behavior reviewed:

- Requires root, Linux, x86_64/aarch64/arm64, curl, git and systemctl. Selects
  Python 3.13, 3.12, 3.11, then python3, requiring >=3.11 plus pip and venv.
- Existing `/usr/bin/python3.11` is 3.11.15 with pip 22.3.1 and venv available.
  Default python3 is 3.6.15; leave it unchanged. Git 2.51.0, curl 8.14.1 and
  systemd 254 are present. No OS dependency installation or upgrade was needed.
- Core metadata requires Python >=3.11, hatchling for build, websockets >=12,
  pydantic >=2.6,<3, PyYAML >=6, structlog >=24.1 and protocol Git tag v1.11.0.
  Package resolution/install was not attempted. Dependencies are not all locked.
- Creates `/etc/sentinelx/host_id` unless present, creates system user sentinelx
  with `/bin/false`, and by default offers unrestricted passwordless sudo.
  `SENTINELX_SKIP_SUDO=1` skips creation but does not remove existing grants.
- Deletes an existing install directory before cloning; therefore it is not a
  safe preserve-in-place upgrade procedure. Existing installs require a separate
  identity/config/service-preserving plan, protected backup, and grant audit.
- Clones the core using `git clone --depth 1 --branch "$CORE_REF"`. Despite the
  header's claim, arbitrary commit hashes are not generally valid branch values.
  Do not assume setting CORE_REF to a SHA pins this installer successfully.
- Creates a venv, upgrades its pip, installs editable core and dependencies, and
  recursively gives the sentinelx user ownership of the install directory.
- Downloads the enrollment helper from mutable main and runs it as root; it
  reuses an existing identity. Paste mode uses standard input, no local listener.
  The helper writes identity before the installer applies 0600 and sentinelx
  ownership: use `umask 077` for the entire root operation. The helper does not
  disable terminal echo; the owner must use an unrecorded terminal with echo
  disabled for secret entry and restored afterward. Never use shell tracing.
- Preserves a pre-existing config file; otherwise copies the broad example.
  Creates agent-owned upload and log directories. No Docker group addition was
  found. The generated unit runs as sentinelx and auto-enables/starts immediately.
- The generated service omits `NoNewPrivileges` and filesystem confinement.
  The core repository's separate systemd example has different paths and is
  not the unit installed by this installer. Review the actual generated unit.

## Policy review and release blocker

`config.yaml.candidate` uses the actual Policy schema. It disables exec entirely
and grants no services, write paths, fetch hosts or playbooks. Only bounded reads
of `/proc/loadavg`, `/proc/meminfo` and `/proc/uptime` are selected. No application
evidence directory is exposed because no sanitized publication path was selected.

This template is **not an effective complete read-only policy** for reviewed
core 0.11.14. Findings in `src/sentinelx_core`:

- `policy.py:is_command_allowed` uses raw prefix matching, then exec runs via
  `bash -lc`. Even a seemingly fixed health command prefix can accept appended
  shell syntax; retain an empty command list.
- `handlers/__init__.py:build_registry` registers scripts, uploads and edit
  upload staging unconditionally. No policy switches disable these operations.
- `handlers/script.py:make_script_run_handler` accepts a Policy argument but
  does not use it; script contents are deliberately not allowlist checked.
- Inline uploads and chunk staging are independent of file_ops write grants.
  An empty trusted-fetch list only blocks URL fetches, not inline uploads.
- Root ownership of a disabled staging directory and systemd confinement could
  provide defense in depth, but are not evidence of a supported policy denial.
  No confinement workaround was deployed or certified in this task.

Offline validation uses the real Policy loader, checks positive health paths,
negative secret paths, write denials, exec denials and service-change denials.
An AST-extracted upstream script/upload factory with a filesystem tripwire
confirms both reach filesystem operations without policy rejection. The
tripwire stops before any filesystem operation or subprocess launch; no payload
executes. This is evidence of an enforcement gap, not live certification.

Run from the review checkout:

```bash
python3.11 operations/sentinelx/server-b/validate_review.py \
  /home/codestra-admin/artifacts/sentinelx-install-review-20260905/core
```

Before proceeding, obtain and review official agent support for denying scripts,
all upload/staging/transfer writes, and forbidden operations before side effects,
or validate a complete equivalent enforcement layer. Re-run offline negative
tests on the exact release and verify all handlers, including audit and transfer
paths. A mere config parse or an unwritable upload directory is insufficient.

## Root continuation after enforcement is resolved

1. Reconfirm hostname, interfaces and effective UID 0. Check for any existing
   agent, user, host ID, policy, identity and unit/drop-ins without exposing
   identity bytes. Preserve existing state and avoid duplicate enrollment.
   Audit all sudoers/group/ACL grants as root; never assume SKIP_SUDO revokes them.
2. Capture sanitized service states and business-write gates. Do not print
   service environments, credentials, customer data, recordings or backup data.
3. Set `umask 077`, then perform the requested root staging and download:

   ```bash
   install -d -m 0700 /root/sentinelx-install
   curl --proto '=https' --tlsv1.2 -fSL \
     https://get.sentinelx.app/install.sh \
     -o /root/sentinelx-install/install.sh
   bash -n /root/sentinelx-install/install.sh
   sha256sum /root/sentinelx-install/install.sh
   ```

4. Re-review changed bytes and mutable core/helper/dependencies. Install only
   proven missing openSUSE dependencies. Pre-create validated root-owned
   `/etc/sentinelx/config.yaml` and root-owned parent directory before installation.
   Sentinelx may read policy but must not write or replace it. Pre-stage and
   validate needed service confinement before the installer auto-starts it.
   Ensure no sudo, Docker socket, policy write or telephony-control grants.
5. Only once all enforcement prerequisites pass, use the authorized command in
   the owner's unrecorded root terminal:

   ```bash
   SENTINELX_SKIP_SUDO=1 SENTINELX_ENROLL_MODE=paste \
     bash /root/sentinelx-install/install.sh
   ```

   The helper prints an official URL of the form
   `https://mcp.sentinelx.app/auth/dashboard/enroll?host_id=<actual-host-id>`.
   Use the same account as this session's connected SentinelX app. Present the
   actual generated URL; do not invent an ID. Owner enters the token directly
   into the terminal with echo disabled, never ChatGPT, command arguments, logs,
   commits or shared artifacts. If incomplete, retain protected install state
   and report `BLOCKED_OWNER_ENROLLMENT` without claiming service readiness.
6. Confirm service active/enabled and runtime user sentinelx, actual policy and
   confinement, and no unrestricted grants. Core uses authenticated outbound
   `wss://mcp.sentinelx.app/agent/connect` with a Bearer header and expects a
   `welcome`. Verify a sanitized successful handshake, then list hosts through
   this session's connected account and match actual host ID and machine facts.
   Apply requested dashboard label only to that verified host.
7. Verify allowed health reads and forbidden reads/writes/scripts/uploads/service
   changes are rejected before execution using synthetic canaries and mocked
   side-effect tests first. Do not submit destructive tests against telephony.
   Compare service states, configuration hashes and business gates to baseline.
   Never equate systemd active with authenticated account enrollment.

## Repository review

Authoritative infrastructure repository:
`appolon1908-hue/codestra-production-platform`, established by
`docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md`. The target branch
`release/production-activation` is protected. This report uses an isolated review
branch based on `e44decce67b8bc292753d77a82ca21c9fa37af0f`; submit through a PR,
do not merge or deploy it automatically. Only sanitized review files belong in
the PR; downloaded upstream source, identity, tokens and secret material do not.
