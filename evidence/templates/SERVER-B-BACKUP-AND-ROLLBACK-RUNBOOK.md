# Server B backup and rollback runbook

This controlled runbook is validated only against disposable synthetic files.
Server B paths and commands require active-baseline reconciliation and separate
authorization.

Backup scope is an explicit allowlist: generated manager configuration, TLS
leaf certificate, chain, and private key. Record SHA-256, numeric ownership,
and mode before change. Create a timestamped mode-0700 directory and a
mode-0600 `SHA256SUMS`; verify it before applying any change.

Exact disposable restore operation:

```text
for each allowlisted relative path:
  copy2 BACKUP/<relative-path> RUNTIME/<relative-path>
  chmod RUNTIME/<relative-path> <recorded-mode>
verify every restored SHA-256 and mode equals the pre-change manifest
restart the disposable TLS proxy/container
wait for Asterisk CLI health
verify TLS CA and hostname
verify AMI authentication and denial matrix
```

Rollback triggers: checksum mismatch, TLS validation failure, AMI authentication
failure, denial action success, PID change during denial testing, unexpected
channel/call, secret leakage, or unexpected network contact. Restore the TLS
proxy before validating the test gateway. Prefer Asterisk health validation
without restart where topology permits; the single-process disposable image is
restarted solely to reload its synthetic proxy material. Maximum rollback time
is ten minutes.

`BASELINE_BACKUP_SCOPE_GATE=PASS`
`BASELINE_BACKUP_CHECKSUM_PLAN_GATE=PASS`
`BASELINE_BACKUP_PROTECTION_GATE=PASS`
`BASELINE_ROLLBACK_TRIGGER_GATE=PASS`
`BASELINE_ROLLBACK_ORDER_GATE=PASS`
`BASELINE_ROLLBACK_HEALTHCHECK_PLAN_GATE=PASS`
