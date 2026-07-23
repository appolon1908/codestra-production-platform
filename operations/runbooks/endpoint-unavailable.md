# Endpoint unavailable

1. Confirm the failing probe and TLS result from Prometheus.
2. Check only the affected container, reverse-proxy route, and dependency.
3. Preserve logs and current container/image identity before restarting.
4. Use the smallest service restart scope.
5. Confirm recovery notification and reconcile any queued events.

