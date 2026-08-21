# Restricted production operator

This package installs the root-owned forced-command interface used by the
protected `production-activation.yml` workflow. It does not grant a shell,
accept paths, or accept arbitrary commands. The request grammar is exactly:

```text
ACTION PROTECTED_SHA IMAGE_DIGEST CHANGE_ID MAINTENANCE_DATE
```

The allowlist is `preflight`, `backup`, `validate-backup`, `restore-test`,
`stage`, `canary`, `status`, `rollback`, and `collect-evidence`. State-changing
actions are denied outside 00:00–04:00 America/New_York on the installed date.

`stage` pulls the configured immutable digest using a credential received on
standard input and creates only `codestra-production-standby-approved` on
Docker network mode `none`. It never changes the active middleware container,
Kong routes, Caddy, Server B, telephony, providers, databases, or production
traffic. A failed start remains a failed standby certification gate.

The installer adds one forced-command key and one sudoers command. OpenSSH
`restrict` disables forwarding, agent forwarding, X11 and PTY allocation. The
operator replaces the inherited environment, locks concurrent execution,
binds every call to `/etc/codestra/production-operator/release.json`, and writes
secret-free JSON audit records.

Use only the checksum-pinned root-console command published with the reviewed
PR evidence. Never grant `NOPASSWD: ALL` or install an unrestricted runner.
