# Code structure and refactor rules

## Goal

Make each subsystem understandable without reading deployment files, monolithic HTTP handlers, workflow JSON, and historical reports at the same time.

## Target service layout

```text
service_name/
  api/
    dependencies.py
    errors.py
    schemas/
    routes/
  application/
    commands/
    queries/
    services/
  domain/
    models.py
    policies.py
    events.py
  infrastructure/
    database/
    providers/
    queues/
  workers/
  observability/
  settings.py
```

The names may vary by framework, but the boundaries are mandatory.

### `api/`

Owns transport concerns only: parsing, authentication context, request/response schemas, status-code mapping, and delegation to application use cases. It must not contain SQL, provider calls, workflow state machines, or long-lived retry loops.

### `application/`

Owns use cases, transaction boundaries, commands, queries, idempotency coordination, and authorization decisions that depend on domain state.

### `domain/`

Owns business invariants and state transitions. It must not import HTTP, Docker, Kong, Caddy, Odoo RPC, n8n, or provider SDKs.

### `infrastructure/`

Owns PostgreSQL, SQLite, Redis, NATS, Odoo, n8n, Keycloak, VICIdial, Klyrow, Telnexa, and Kyqra adapters. Adapters implement application-defined interfaces and have bounded timeouts/retries.

### `workers/`

Owns durable background execution. Workers claim work using an authoritative lease/fencing model, preserve tenant/correlation/idempotency context, and record terminal/dead-letter state.

### `observability/`

Owns health, readiness, metrics, safe structured logging, and release identity. Readiness must fail closed when a required dependency is unavailable.

## Control-plane decomposition

`control_plane_service/server.py` currently combines authentication, health, CRM, forms, messages, crawler, event ingestion, admin APIs, error mapping, and HTTP transport. Refactor it through focused PRs in this order:

1. Extract shared response/error/request-context helpers without behavior changes.
2. Extract gateway and operator authentication into `api/dependencies.py`.
3. Extract system/health/admin routes.
4. Extract event and webhook ingress.
5. Extract communications and crawler routes.
6. Extract CRM and forms routes.
7. Replace the hand-written dispatcher with a small application factory.
8. Preserve exact contract tests at every step.

No PR should mix this decomposition with a production migration or feature activation.

## API implementation rules

- One versioned request schema and response schema per public mutation.
- One stable machine-readable error envelope.
- `X-Request-ID` and `X-Correlation-ID` are preserved or generated at the edge.
- Tenant context is selected by the client but validated by the owning service.
- Mutations require an idempotency policy unless a documented exemption exists.
- Provider callbacks require authentication, replay protection, payload bounds, and durable inbox handling.
- Route definitions use stable service aliases, not generated container names.
- Feature flags are declared once in the feature catalog and mapped to runtime configuration.

## Repository hygiene

- No new source file should exceed 500 lines without an architecture exception.
- No new PR should change more than one release boundary unless it contains an indivisible migration.
- Generated files must identify their generator and are validated for drift.
- Runtime evidence, backups, logs, certificates, and secrets are never committed.
- Superseded source remains discoverable through Git history; it should not stay as an active merge candidate.
