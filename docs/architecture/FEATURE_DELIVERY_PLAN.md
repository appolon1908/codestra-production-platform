# Feature delivery and cleanup plan

The platform should be improved through a small number of ordered, focused PRs. Do not send the current collection of stacked drafts directly to a server.

Every gap required before server push must name at least one affected catalog
feature. A resolved gap must cite tracked JSON under
`evidence/catalog-gaps/<gap-id>/` with schema
`codestra.catalog-gap-resolution.v1`, the exact gap ID and source SHA, a UTC
observation time, and a non-empty proof-artifact list. General documentation or
unrelated evidence cannot clear a deployment blocker.

## Phase 1 — structure and catalog

- Establish the platform service/feature/API catalog.
- Replace the root README and architecture overview with current boundaries.
- Add catalog validation to the normal test suite.
- Record source, runtime, and governance gaps explicitly.

## Phase 2 — API authority and coverage

- Finish the Kong route-authority PR and eliminate name-only trust.
- Make one route registry reference dedicated security profiles rather than duplicating them.
- Complete control-plane OpenAPI coverage for every implemented public/private route.
- Add exact error, request-ID, scope, tenant, idempotency, and rate/size contracts.
- Add a read-only API coverage report to CI.

## Phase 3 — control-plane modularization

Split `control_plane_service/server.py` without changing behavior:

1. common HTTP context and errors;
2. authentication dependencies;
3. health/admin routes;
4. events/webhooks;
5. communications/crawler;
6. CRM/forms;
7. application factory and route registration.

Each extraction requires regression tests and must remain source-only until the complete service image is rebuilt from a protected merge.

## Phase 4 — runtime service normalization

- Replace generated container names in contracts with stable service/network aliases.
- Consolidate authoritative Compose files and document override order.
- Create one feature-flag registry and validate runtime settings against it.
- Add healthchecks for every long-running request or delivery worker.
- Keep host Caddy, upstream-gateway, Kong, application services, and databases as separate release units.

## Phase 5 — missing feature/API delivery

Deliver missing capability groups in separate PRs:

- versioned control-plane admin and operations APIs;
- complete communication message timeline and reconciliation APIs;
- provider event/DLR contracts and durable inbox translators;
- post-call follow-up core, API, realtime, delivery, automation, analytics, and UX in dependency order;
- WebSocket/agent session and reconnect contracts;
- provisioning identity, secrets, monitoring, backup timers, and production readiness;
- generated SDKs from merged OpenAPI contracts.

The exact product behavior for a missing feature must come from its reviewed source specification. The gap register does not invent business rules.

## Phase 6 — recovery and production preparation

- Complete shared PostgreSQL PITR and the coherent HA decision.
- Complete Kong database replica/DNS/fencing/secret authority separately.
- Build signed immutable artifacts from protected merged SHAs.
- Run staging migration, rollback, canary, soak, and live-versus-Git checks.
- Deploy only the features whose catalog blockers are resolved.

## Pull-request rules

- One parent PR per feature foundation.
- Child PRs state their exact parent and merge order.
- A child is retargeted only after the parent merges and then receives fresh CI/review.
- Documentation-only missions do not remain beside completed implementation as active release candidates.
- Superseded PRs are closed after their accepted evidence is preserved.
