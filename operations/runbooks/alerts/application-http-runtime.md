# Application HTTP runtime alert

Identify the `application`, `instance`, and release labels from the alert. Check
the private readiness endpoint, then the dependency-specific logs using the
correlation ID. Do not print credentials or request headers.

For readiness failures, validate the authoritative database or registry before
restarting anything. For HTTP 5xx or latency alerts, compare the exact deployed
digest with the production source lock and inspect bounded application metrics.
Keep every external-effect capability disabled during diagnosis.

If rollback is required, use only the protected rollback digest and procedure
recorded for the active release. Verify readiness and alert recovery after the
rollback.
