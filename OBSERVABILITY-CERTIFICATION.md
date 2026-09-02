# Observability certification

Result: **FAIL**

The refreshed Server 65 baseline contains 20 production or unclassified runtime OpenAPI applications. Only 2/20 have runtime evidence for health, readiness, and metrics coverage. The prior `4/20` numerator included an explicitly staging application and a non-container Caddy proxy observation; the exact membership and missing paths are recorded in `evidence/server65/OPENAPI-MONITORING-COVERAGE-20260902.yaml`. End-to-end log, trace, alert-delivery, acknowledgement, dashboard label, queue depth, outbox age, dead-letter, provider failure, authentication failure, backup failure, certificate expiry, and disk-pressure evidence is incomplete.

Source reconciliation now proves that the canonical Middleware runtime factories
provide health, readiness, and real Prometheus metrics for the 16 Middleware
applications. The platform-owned mail API and reseller portal source candidates
now add real request counters and latency histograms, dependency-sensitive
readiness, private Prometheus targets, and availability/5xx/latency/dependency
alerts. This makes the 20/20 endpoint contract source-complete, but it does not
change the runtime numerator: exact-digest promotion, successful target read-back,
alert delivery, and acknowledgement remain mandatory before PASS.
