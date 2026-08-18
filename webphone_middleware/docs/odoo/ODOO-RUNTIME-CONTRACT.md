# Odoo runtime contract

Odoo exposes authenticated health readiness, versioned capabilities, outbox claim/read/renew/ack/fail/release, result create/read/reconcile, desired-state reads, trace, audit, and metrics. Service JWTs require exact issuer, audience, client allowlist, scope, expiry, and signature. Replay-sensitive requests additionally bind timestamp, nonce, body SHA-256, trace context, request, correlation, causation, and idempotency identifiers.

Required least-privilege scopes are `odoo.integration.outbox.claim`, `.read`, `.renew`, `.acknowledge`, `.fail`, `odoo.integration.results.write`, desired-state/read scopes, `monitor.read`, and `service.attest`. A credential covering one operation must not imply another.

The sync worker negotiates capabilities before every claim cycle. It accepts only
canonical payloads whose SHA-256 matches the Odoo envelope, commits the event and
redacted audit record to PostgreSQL, then acknowledges the lease. Concurrent
duplicate intake is resolved by the durable unique Odoo event ID; a changed hash
for that ID is a permanent conflict.

The staging source of truth is `Codestra-SRL/codestra-odoo-addons` at the reviewed `main` commit. The deployment mount is `/root/codestra-ai-platform-source-20260801T210000Z/codestra-odoo-addons:/mnt/extra-addons:ro`.
