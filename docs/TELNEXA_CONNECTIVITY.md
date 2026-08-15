# Telnexa Connectivity

Outbound simulator evidence: `TELNEXA_MODE=simulator` returns a unique `sim-*` ID, transitions the ledger to accepted, and performs no network call. Production requires both global authorization and a private URL/token.

Inbound evidence: service-key and HMAC validation, fresh/stale timestamps, replay dedupe, duplicate DLR handling, inbound MO ledger creation, and STOP suppression pass locally. Billing units are recorded without duplicate usage rows. Production Jasmin, balance, DLR latency and provider credentials remain BLOCKED by middleware access.
