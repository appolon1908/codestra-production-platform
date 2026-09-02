# Observability certification

Result: **FAIL**

The refreshed Server 65 baseline contains 20 production or unclassified runtime OpenAPI applications. Only 2/20 have runtime evidence for health, readiness, and metrics coverage. The prior `4/20` numerator included an explicitly staging application and a non-container Caddy proxy observation; the exact membership and missing paths are recorded in `evidence/server65/OPENAPI-MONITORING-COVERAGE-20260902.yaml`. End-to-end log, trace, alert-delivery, acknowledgement, dashboard label, queue depth, outbox age, dead-letter, provider failure, authentication failure, backup failure, certificate expiry, and disk-pressure evidence is incomplete.
