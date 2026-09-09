# Codestra platform architecture

## 1. Authority model

| System | Authority |
| --- | --- |
| Keycloak | Authentication, OIDC clients, machine identities, token issuance |
| Kong | Public API authentication, route selection, rate/request limits, correlation IDs |
| Middleware / control plane | Integration authorization, tenant context, idempotency, inbox/outbox, callback and delivery state |
| Odoo | CRM and approved business desired state; not a provider or telephony execution engine |
| n8n | Non-authoritative asynchronous orchestration through approved middleware APIs |
| VICIdial / Asterisk | Telephony execution behind a restricted adapter |
| Klyrow / Postal | Email policy and transport execution |
| Telnexa / Jasmin | SMS policy and transport execution |
| Kyqra | Governed crawler execution through a private provider API |
| PostgreSQL | Durable application state, separated by database and application role |
| Redis | Authenticated private reconstructible cache/queue/lease state unless reclassified |
| NATS | Private event transport for middleware-owned events |

No application may gain authority merely because it can reach another service or database. Every cross-system call must be registered, authenticated, bounded, tenant-aware where applicable, and observable.

## 2. Edge and routing

```text
Internet
  -> host Caddy :443
  -> loopback Docker upstream-gateway
  -> private Kong proxy
  -> private service alias
```

Host Caddy remains outside Docker and terminates public TLS. The Docker upstream-gateway is an internal routing layer. Kong owns protected business API routing. Middleware, PostgreSQL, Redis, NATS, Kong Admin, and provider-private listeners are not public.

Reviewed exceptions:

- Odoo browser and realtime traffic may pass from Caddy/upstream-gateway directly to Odoo.
- Public `/healthz` and `/readyz` contracts may use a dedicated health-only route.
- Private provider receivers may use source-restricted mTLS Caddy listeners.
- `api.breero.com` is a separately governed exception and must not be normalized without its own route contract and rollback plan.

A direct Caddy-to-middleware business route is prohibited.

## 3. Application boundaries

The target source layout for service code is:

```text
<service>/
  api/              HTTP/RPC transport, validation, authentication adapters
  application/      commands, queries, use cases, transactions
  domain/           business rules and state transitions
  infrastructure/   database, provider, queue, and external-service adapters
  workers/          durable background execution
  observability/    health, readiness, metrics, structured logging
```

Existing monolithic files are migrated incrementally. New features must not add more route, authentication, SQL, provider, and business logic to a single handler module.

## 4. API authority chain

```text
config/platform-catalog.yaml
  -> config/integration-registries.yaml
  -> versioned OpenAPI / JSON Schema
  -> Kong or private-Caddy route authority
  -> application implementation
  -> contract and runtime tests
```

Each API must have one owner and one route authority. A route name alone is never sufficient authority. The contract binds host, method, path, protocol, service alias, authentication, scopes, request limits, idempotency, tenant requirements, error model, request ID, and lifecycle.

## 5. Data and consistency

- Each database has one owning application role.
- Applications do not connect directly to another application's database.
- Mutations use idempotency and optimistic or explicit concurrency control.
- Durable external delivery uses outbox/inbox state with bounded retries and dead-letter visibility.
- Redis is not promoted to durable authority without an owner-approved recovery and HA policy.
- Database migrations require a fresh encrypted off-host backup, isolated restore/migration rehearsal, rollback compatibility decision, and a bounded write freeze.
- Shared PostgreSQL production migration remains blocked until current PITR and recovery gates pass.

## 6. Capability lifecycle

Every feature is classified as one of:

- `active`: source and runtime authority are proven.
- `source_ready`: code and contracts exist; deployment or live evidence is incomplete.
- `staging`: deployed only in a non-production boundary.
- `planned`: contract or implementation is incomplete.
- `deprecated`: retained only for migration/rollback evidence.

Every side-effecting capability has a fail-closed default. Source readiness does not enable SMS, email, crawling, Odoo broad writes, n8n production workflows, VICIdial writes, PSTN dialing, payments, or other external delivery.

## 7. Release units

A production release should contain the smallest coherent unit:

1. Contract and implementation source.
2. Required migration.
3. Exact immutable artifact.
4. Service-specific Compose change.
5. Monitoring and rollback evidence.

Recreate only affected services. Do not replace host Caddy, upstream-gateway, Kong, PostgreSQL, and middleware together. Reload Caddy only when its validated configuration actually changes.

## 8. Current structural priorities

The source is functional but still has structural debt recorded in `config/platform-catalog.yaml`:

- duplicate/overlapping API route authorities;
- incomplete control-plane OpenAPI coverage;
- a large control-plane HTTP handler that needs modular decomposition;
- generated Docker container names used as service identities in several contracts;
- feature flags and Compose overlays spread across multiple authorities;
- historical pull-request and report lineage mixed with current release work;
- runtime recovery/identity/secret gates that remain intentionally fail closed.

These gaps must be addressed through focused PRs before treating the repository as a clean production deployment package.
