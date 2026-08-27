# Codestra Runtime Integration Fabric v2

This repository composes reviewed immutable service releases. It does not own application business logic.

## Public path

```text
Internet -> Caddy -> selected Kong data plane -> Middleware -> authoritative service
```

Caddy owns public certificates, exact host allowlists, redirects, HSTS/basic edge headers, and forwarding to the selected Kong cell. Kong owns API host/path/method routing, authentication enforcement, request/rate limits, upstream health, and API telemetry. Middleware owns tenant authorization, contracts, commands, inbox/outbox, provider adapters, audit, and reconciliation.

## Runtime cells

### Core communications

Odoo, Klyrow, Telnexa, Postly, Kyqra, public forms, provisioning, and non-financial operational APIs.

### Beyvra financial isolation

A separate Kong control/data plane, Kong database, rate-limit namespace, n8n database, n8n Redis namespace, encryption key, service identities, and observability namespace. n8n may reach only the non-financial `beyvra.operations.*` surface through Middleware.

### Private telephony

Private Kong data plane reachable only from approved Middleware addresses over the VLAN. VICIdial/Asterisk commands and callbacks remain behind the restricted adapter. No public telephony listener or live dialing is enabled.

## Network zones

- `edge-public`: Caddy only on 80/443.
- `gateway-core-private`: Caddy to core Kong data plane.
- `gateway-beyvra-private`: Caddy to Beyvra Kong data plane.
- `gateway-telephony-private`: Middleware to private telephony Kong/adapter.
- `middleware-control-private`: Kong and n8n to Middleware.
- `automation-core-private`, `automation-beyvra-private`, `automation-telephony-private`: isolated n8n cells.
- `provider-vlan-private`: approved Middleware/adapters to provider host and telephony server.

Kong Admin API, Kong Manager, cluster endpoints, n8n editor/API, databases, Redis, NATS, Temporal, provider engines, and adapter administration are never public.

## Promotion

```text
source contract -> exact-head CI -> independent review -> protected merge
-> immutable image/config artifact -> inactive staging import -> no-effect E2E
-> backup/restore and rollback -> inactive production import
-> separate workflow activation -> separate capability canary
```

Staging and production use identical application digests but separate databases, Redis namespaces, secrets, certificates, and release manifests.

## Safety

This architecture branch does not change Caddy, Kong, Compose, DNS, firewall, database, container, workflow, provider, or live capability state.
