# Security

Each of Kyqra, Telnexa, Klyrow, n8n, and Odoo has a distinct API key and HMAC secret. Service API keys may be stored as per-service SHA-256 digests (`*_MIDDLEWARE_API_KEY_SHA256`); rollout-compatible plaintext variables must be left empty when a digest is configured. Requests sign `timestamp + newline + event_id + newline + source + newline + exact_body` with HMAC-SHA256. Middleware uses constant-time comparisons, a five-minute window, unique event IDs, scoped idempotency, body-conflict rejection, maximum body size, and server-side tenant filtering.

Operator roles are `platform_admin`, `operations`, `support`, `auditor`, and tenant-scoped `tenant_admin`. Replay, integration pause/resume, and preference changes are audited. Runtime secrets live in `/etc/codestra/secrets/control-plane.env` with mode 0600 and are excluded from Git. Rotate identities independently, deploy both ends during an overlap window, run valid/invalid/replay tests, and revoke the old value. Never log tokens, signatures, credentials, or authorization headers.

The service binds only to loopback. Databases, NATS, Redis, n8n internals, and Docker remain private. Existing UFW and the private mTLS ingress are preserved.
