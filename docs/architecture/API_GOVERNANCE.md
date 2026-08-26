# API governance

## Canonical authority

The platform API authority is layered, not duplicated:

1. `config/platform-catalog.yaml` identifies the feature, owner, lifecycle, ingress, and critical API surface.
2. `config/integration-registries.yaml` identifies detailed connector, endpoint, webhook, protocol, retry, and ownership contracts.
3. OpenAPI and JSON Schema define payloads and responses.
4. Kong or a reviewed private Caddy listener defines network ingress.
5. Application code implements the contract.
6. CI and runtime canaries prove the layers agree.

A generic route inventory may verify a dedicated security manifest, but it must not overwrite plugin configuration from a route name or an empty config object.

## Required API fields

Every public or private service API records:

- stable API ID and owner;
- lifecycle and feature ID;
- host, method, path, protocol, and exposure;
- ingress (`kong`, browser Caddy, health-only Caddy, private mTLS, or internal service);
- stable upstream service alias;
- authentication and required scopes/roles;
- tenant and campaign context requirements;
- idempotency and replay policy;
- request size and rate limits;
- request/response schema;
- request/correlation ID behavior;
- error envelope;
- implementation and route-authority source;
- deprecation/sunset information when applicable.

## Public edge rules

- Public business APIs enter through Kong.
- Kong Admin and internal service ports are never public.
- Public health routes expose no secrets, dependency topology, or customer data.
- Browser application routes may terminate at Caddy/upstream-gateway when that boundary is intentional and documented.
- Private provider ingress requires private addressing plus mTLS or an equivalently reviewed service identity.
- Direct Caddy-to-middleware business routing is prohibited.

## Authentication and authorization

- Human access uses Authorization Code + PKCE through Keycloak.
- Machine access uses short-lived client credentials or a reviewed private mTLS/HMAC identity.
- The canonical issuer is `https://auth.codestra.co/realms/codestra` for realm tokens.
- Gateway scope enforcement is not a replacement for application authorization.
- Tenant and record-level authorization remain authoritative in the owning application.
- Unknown route/scope combinations fail closed.

## Mutations

Mutating APIs must define:

- `Idempotency-Key` semantics;
- conflict behavior for same key/different payload;
- transaction and concurrency behavior;
- durable audit/outbox/inbox behavior where external effects occur;
- retryable and terminal error classes;
- bounded timeout and retry policy;
- safe reconciliation/readback.

## Errors

New APIs use a stable envelope:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "safe summary",
    "request_id": "...",
    "correlation_id": "...",
    "details": {}
  }
}
```

Do not return stack traces, credentials, SQL, provider secrets, or private topology.

## Versioning and deprecation

- Breaking changes use a new versioned contract.
- Legacy hosts and paths are disabled by default and require an owner, sunset date, monitoring, and rollback plan.
- A compatibility shim has an explicit removal date.
- Generated clients are built from the exact merged OpenAPI SHA.

## Release gate

Before a route or API reaches a server:

1. Catalog and registry validation pass.
2. OpenAPI/schema validation pass.
3. Implementation contract tests pass.
4. Kong/Caddy dry-run reconciliation reports zero unexpected routes.
5. Authentication, scope, tenant, idempotency, rate, size, and request-ID canaries pass.
6. Rollback and live-versus-Git reconciliation are recorded.
