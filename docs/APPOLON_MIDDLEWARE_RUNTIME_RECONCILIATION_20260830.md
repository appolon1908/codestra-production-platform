# Appolon Middleware production runtime reconciliation

Status: repository aligned, not applied.

The controlling production Compose project was discovered read-only from the
running `middleware-integration-api` service. Its assembled configuration is
owned by `/opt/codestra/compose` plus protected release overrides. No live file,
container, network, database, or secret was changed during discovery.

## Captured legacy runtime

- Service: `middleware-integration-api`
- Generated container: `codestra-middleware-integration-api-1`
- Previous image digest: `sha256:09d4bd0f7b2376e0a06d3efae27a6642429389fa7e3277791ec0b36584e87175`
- Previous command: `/opt/venv/bin/python -m app.entrypoints.integration_api`
- Previous internal port: `8095`
- Existing stable network alias: `middleware-integration-api`

The previous digest and command are rollback evidence only. They are not an
approved source or build input for the canonical runtime.

## Canonical side-by-side manifest

`deploy/middleware/compose.appolon-integration-api.yaml` adds the distinct
`appolon-middleware-integration-api` service, pins the signed image from
`appolon1908-hue/Middleware-`, uses its default entrypoint and port `8080`, and
exposes no host port. Kong reaches the new N8N control-plane runtime only
through the external private `codestra-kong_kong_backend` network and stable
alias `middleware-integration-api`.

The frozen deployment candidate is source
`c4fb367577581f004745760c83963cdd96ed518e`, signed release run
`33306692194`, and immutable image digest
`sha256:83e6fd7d6e824a6259b574f0aacbbf08dc58f4419caf0193344d61e5717d5d63`.
Its recorded build time is `2026-08-30T10:31:49Z`. The manifest selects the
image's fail-closed `codestra-middleware-production-v1` runtime profile.

The first protected start reached PostgreSQL but stopped before serving because
the legacy `codestra_middleware` database reports unrelated Alembic revision
`0054_campaign_actions`. The canonical migration tool refused to guess or stamp
that lineage and applied no migration. The failed side-by-side container was
removed; the legacy runtime remained healthy. The captured Compose topology
identified dedicated database `codestra_middleware_appolon` and role
`appolon_middleware_api` as the required isolation boundary. Those values
remain recorded in the release lock. Because the frozen image's built-in
production profile uses different dependency DNS and TLS requirements, a
separate protected topology review remains mandatory; this repository
alignment does not authorize an apply.

The healthy legacy service remains in place on port `8095` for its 132-route
contract. Existing callback, campaign, and control-plane health consumers keep
their legacy generated hostname and port until their contracts are separately
certified against the Appolon runtime. At protected apply time the stable alias
must be removed from the legacy container before the new service joins Kong's
network, preventing ambiguous Docker DNS while preserving legacy-name traffic.

The backend and identity networks are retained for PostgreSQL, Redis, and
Keycloak reachability. Legacy provider, Odoo-staging, provisioning, admission
wrapper, and service-specific credential mounts are deliberately not copied:
they belong to the older runtime and are not dependencies declared by the
signed appolon image. Runtime credentials and webhook secrets must be supplied
only by `/etc/codestra/secrets/appolon-middleware-production.env`, which is an
external protected deployment input and is never stored in Git.

All canonical external-effect flags are explicitly disabled in the manifest,
overriding any legacy value in the protected env file. Deployment requires a
separate protected review and apply after configuration, DNS, authentication,
route, rollback, and readiness validation. This change does not authorize that
apply.
