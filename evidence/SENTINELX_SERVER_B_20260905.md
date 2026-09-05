# SentinelX Server B evidence — 2026-09-05

## Observed host and access

- Target hostname: `static`
- Public/private network identity: `65.21.67.207` / `10.40.0.2`
- OS: `openSUSE Leap 15.6`; kernel `6.4.0-150600.23.103-default`; x86_64
- Effective remote identity: `uid=1001(codestra-admin) gid=1001(codestra-admin)`
- Authorized SSH alias: `codestra-vicidial`; strict host-key checking enabled
- Root access result: unavailable. The sudo policy explicitly denies general
  elevation and permits only named `codestra-vicidial-operator` actions.
- Existing SentinelX evidence visible to the operator: systemd unit not found,
  `/etc/sentinelx` not found, `sentinelx` account not found, CLI not found.
  Root-only locations could not be conclusively inspected without root.

## Installer and source review

- Official installer URL: `https://get.sentinelx.app/install.sh`
- Installer shell syntax: PASS (`bash -n`)
- Installer SHA-256:
  `56f5da769567a471ccf798fa11105f747738f26ee48d0d106922922e56d3acb9`
- Installer repository HEAD reviewed:
  `e637b12c35e40a81fef3171394fe863235575dfb`
- Core repository HEAD reviewed:
  `d6b33822b61e7fccf39547d5cce8add8bc7021f9`
- Core declared version: `0.11.14`
- The live installer did not byte-match the installer repository's
  `install.sh` at that HEAD (live file was 1,004 lines larger in the diff).
- Dependencies actually present: `/usr/bin/python3.11` (`3.11.15`, pip and
  venv imports pass), Git `2.51.0`, curl `8.14.1`, systemd `254`.
- Missing dependencies: none observed; no package change is required.

Review findings: default sudo setup is unrestricted passwordless root; skip
mode does not remove an old sudoers file; core installation deletes the old
code directory; enrollment helper is downloaded from mutable `main`; default
configuration is broad; generic exec uses `bash -lc` with string-prefix
authorization; `script_run` is not governed by `allowed_commands`; upload and
edit-upload handlers remain registered. The proposed policy therefore uses
deny-all commands/services and a root-owned unwritable staging base.

## Unchanged telephony baseline

Before any SentinelX change, these were enabled and active: `asterisk.service`,
`vicidial.service`, `codestra-vicidial-adapter.service`, and
`codestra-vicidial-restricted-adapter.service`. Only approved read-only
`status` and `inventory` actions were run. No telephony configuration,
firewall, SSH, account, or business-write setting was changed.

## Required result fields

```text
HOSTNAME=static
HOST_ID=NOT_CREATED
AGENT_VERSION_OR_COMMIT=NOT_INSTALLED
INSTALLER_SHA256=56f5da769567a471ccf798fa11105f747738f26ee48d0d106922922e56d3acb9
SERVICE_ACTIVE=false
SERVICE_ENABLED=false
RUN_AS_USER=NOT_INSTALLED
HUB_CONNECTION_VERIFIED=false
OWNER_ACCOUNT_ENROLLMENT_VERIFIED=false
READ_ONLY_POLICY_VERIFIED=false
UNRESTRICTED_SUDO_PRESENT=UNKNOWN_ROOT_INSPECTION_REQUIRED
TELEPHONY_CONFIGURATION_CHANGED=false
FINAL_STATUS=BLOCKED_ROOT_ACCESS
```

Exact remaining step: an already-authorized root administrator must log in to
`static`, conclusively inspect root-only SentinelX paths and sudoers, then
execute the reviewed runbook beginning with creation of
`/root/sentinelx-install`. Do not modify `codestra-admin` sudo rights.
