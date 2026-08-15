# Middleware and n8n control-plane architecture

The existing private ingress at `10.40.0.1:8095` remains the production entry for Kyqra, Telnexa, and Klyrow. The control-plane service is an additive, loopback-only management and contract engine at `127.0.0.1:8096`. It never connects to Odoo PostgreSQL or n8n's database.

Events pass through independent API-key and HMAC identities, versioned envelope validation, replay/idempotency storage, tenant scoping, correlation tracking, consent policy, durable queue states, bounded retry/DLQ, and audited operations. Approved adapters call Odoo HTTP/service APIs and governed internal n8n webhooks. Outbound delivery defaults off. Existing NATS JetStream remains the platform event transport; the local state store provides control metadata and deterministic recovery.

Authority remains: Odoo for business desired state, middleware for integration/security state, n8n for orchestration, VICIdial for telephony execution, and the restricted VICIdial adapter for local mutations.
