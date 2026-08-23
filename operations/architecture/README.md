# Runtime integration architecture audit

The timer captures secret-free container/network/listener facts every 15 minutes,
validates them against the protected constitution, preserves evidence, and exports
`codestra_integration_architecture_critical_findings`. Any positive value pages
operations through `CodestraIntegrationArchitectureViolation` and causes the
audit service to fail. Deployment must install an immutable protected release at
`/opt/codestra/integration-constitution/current`; it must not point this path at a
working tree.

Install only through the governed platform release. Validate with `systemd-analyze
verify`, start the service once, confirm its evidence and Prometheus metric, then
enable the timer. Do not suppress findings to make the unit green.
