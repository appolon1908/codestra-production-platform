# Retry, DLQ, and replay

The event worker uses bounded exponential backoff (`2^attempt`, capped at 300 seconds) and five attempts by default. Exhausted events enter durable `dead_letter`. Authorized operators may replay; every replay is audited. Provider dispatch is likewise bounded, and independent circuits open after three failures then allow a half-open probe after 30 seconds.

Odoo, n8n, Telnexa, and Klyrow have independent circuit state, so one degradation does not fail the service. Operators inspect summary, events, and correlation history through the RBAC operations APIs.

## Live audit addendum — 2026-08-15

The safe live harness proved queue insertion and simulator/test dispatch. The full repository suite exercised retry, dead-letter advisory forwarding, effective-once delivery, circuit state, and replay: 191 tests and 9 subtests passed. Both deployed SQLite stores use persistent named volumes.

A production container/worker restart and five-failure exhaustion were not forced because that could disrupt unrelated traffic. Therefore persistence across a production restart and live terminal-DLQ transition remain `BLOCKED-SAFETY`, not PASS. Defaults observed in source are five attempts, capped exponential backoff, three failures to open a provider circuit, and a 30-second half-open cooldown.
