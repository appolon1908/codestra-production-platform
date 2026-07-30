# Server B rollback health-check plan

After rollback, validate file checksum/ownership/mode, TLS chain and hostname,
AMI authentication, expected read events, the complete write-denial matrix,
stable service PID where no restart was approved, zero calls/channels, and zero
external delivery. Any failed check keeps implementation blocked.

`BASELINE_ROLLBACK_HEALTHCHECK_PLAN_GATE=PASS`
