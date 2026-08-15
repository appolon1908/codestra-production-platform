# Retry, DLQ, and replay

The event worker uses bounded exponential backoff (`2^attempt`, capped at 300 seconds) and five attempts by default. Exhausted events enter durable `dead_letter`. Authorized operators may replay; every replay is audited. Provider dispatch is likewise bounded, and independent circuits open after three failures then allow a half-open probe after 30 seconds.

Odoo, n8n, Telnexa, and Klyrow have independent circuit state, so one degradation does not fail the service. Operators inspect summary, events, and correlation history through the RBAC operations APIs.
# Connectivity audit evidence

The 2026-08-15 safe audit executed bounded retry, exponential backoff, dead-letter transition, authenticated manual replay, replay audit, circuit threshold/open/cooldown/recovery behavior, and idempotent event/message processing in the local suite. Real JetStream restart survival remains BLOCKED without an isolated audit URL and credentials; no production queue was purged or restarted.
