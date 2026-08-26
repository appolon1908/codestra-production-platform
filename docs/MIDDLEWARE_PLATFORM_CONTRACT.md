# Canonical middleware platform contract

This document is the production control contract. Service-specific documents may narrow it but must not weaken it.

## API registry

| Public prefix | Capability | Boundary | Durable truth |
|---|---|---|---|
| `/v1/sms` | bounded SMS submission/status | Caddy -> Kong -> SMS middleware | PostgreSQL |
| `/v1/email` | bounded reseller email/status | Caddy -> Kong -> email middleware | PostgreSQL required before certification |
| `/v1/crm` | bounded lead/activity/account API | Caddy -> Kong -> CRM middleware -> Odoo | PostgreSQL mapping/audit plus Odoo ORM |
| `/v1/webhooks` | authenticated bounded webhook ingress | Caddy -> Kong -> event gateway | PostgreSQL event ledger/outbox |

Raw Odoo RPC, arbitrary models, n8n editor/API, provider administration, and VICIdial administration are not public customer APIs. VICIdial callbacks retain their dedicated mTLS and exact-source private route.

## Service registry

The production registry consists of Kong as the public authentication/routing boundary; the integration control plane/event gateway; channel-specific SMS and email APIs; CRM/Odoo adapter; authenticated n8n delivery worker; restricted VICIdial adapter; bounded scraper adapter; PostgreSQL for durable business truth; and Redis only for ephemeral queues/cache/leases. Each deployed role must record its immutable image digest, Compose service, database/schema, queue, required dependencies, owner, and rollback release in the release inventory.

## Common request and error contract

Clients may supply `X-Correlation-ID`; otherwise Kong creates one. Middleware preserves it through events, retries, audits, and downstream calls. Create operations require an `Idempotency-Key` scoped by tenant and operation. The same key plus the same canonical request returns the original result; the same key with different content returns `409`.

Errors are JSON objects containing a stable machine-readable `error`, the correlation ID, and no credential or downstream stack details. Authentication/authorization use 401/403, schema and allowlist failures 422, missing tenant-scoped resources 404, idempotency conflicts 409, throttling 429, and controlled unavailable dependencies 503.

Retries are bounded exponential backoff, default maximum five attempts and 300-second cap. Unsafe creates are retryable only behind durable idempotency. Each downstream has an independent circuit: open after three consecutive failures, then one half-open probe after 30 seconds. Exhaustion enters the durable DLQ; operators re-drive the same event identity through the governed mechanism.

## Health contract

Every activated HTTP service must expose unauthenticated `GET /livez` for process liveness and `GET /readyz` for its required dependencies. A disabled optional integration is reported as disabled and must not make an unrelated API unready. Legacy `/health`, `/ready`, and provider-specific endpoints may remain as compatibility aliases but are not canonical.

## Feature and delivery gates

API availability is controlled independently:

- `SMS_API_ENABLED`
- `EMAIL_API_ENABLED`
- `CRM_API_ENABLED`
- `WEBHOOK_API_ENABLED`
- `VICIDIAL_INTEGRATION_ENABLED`

External delivery is separately denied unless its own gate is true:

- `LIVE_SMS_DELIVERY`
- `LIVE_EMAIL_DELIVERY`
- `LIVE_PSTN_DIALING`

Enabling an API never implies permission to send SMS/email or place a PSTN call. Production deployment defaults all three live-delivery gates to false.

## Tenant mapping

Kong consumer identity maps server-side to a Codestra customer, authorized company/business unit, and bounded downstream identity. Customer payloads cannot choose company IDs, Odoo models, arbitrary fields, provider credentials, or security context. Tenant identity is included in idempotency keys, record lookups, audit rows, and event partitions.
