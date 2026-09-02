# Appolon Middleware production runtime reconciliation

Status: active runtime captured; API-completion replacement pending protected apply.

The controlling production Compose project was discovered read-only from the
running `middleware-integration-api` service. Its assembled configuration is
owned by `/opt/codestra/compose` plus protected release overrides. No live file,
container, network, database, or secret was changed during discovery.

## Captured pre-Appolon legacy runtime

- Service: `middleware-integration-api`
- Generated container: `codestra-middleware-integration-api-1`
- Previous image digest: `sha256:09d4bd0f7b2376e0a06d3efae27a6642429389fa7e3277791ec0b36584e87175`
- Previous command: `/opt/venv/bin/python -m app.entrypoints.integration_api`
- Previous internal port: `8095`
- Existing stable network alias: `middleware-integration-api`

The previous digest and command are rollback evidence only. They are not an
approved source or build input for the canonical runtime.

## Current production runtime captured 2026-09-02

- Service: `appolon-middleware-integration-api`
- Generated container: `codestra-appolon-middleware-integration-api-1`
- Repository: `https://github.com/appolon1908-hue/Middleware-`
- Source revision: `f6748a58f8d2590520a4f28776770957061cdea1`
- Image digest: `sha256:695fa3ce3f50ba4d0ae0784976b946a0a683ca731155e4bd3bd9e90a4670b820`
- Entrypoint: image-default `app.main:create_app`
- Internal port: `8080`
- Database: dedicated `codestra_middleware_appolon`
- Role: dedicated `appolon_middleware_api`

This is the known-good immediate rollback target for the API-completion
deployment. Before migration, protected apply must capture an encrypted,
integrity-verified backup of dedicated database `codestra_middleware_appolon`
at head `0003_immutable_event_ledger`. Rollback must stop the candidate,
restore that verified pre-migration backup into the dedicated database, verify
the restored head is exactly `0003_immutable_event_ledger`, and only then
redeploy this exact digest with the protected Appolon Compose profile and
existing protected environment input. It must verify health, readiness, image
digest, source revision, and schema head after restart. It must not remove the
active service or fall back to the older legacy runtime. The older `09d4bd...`
runtime remains historical recovery evidence only.

## Canonical side-by-side manifest

`deploy/middleware/compose.appolon-integration-api.yaml` adds the distinct
`appolon-middleware-integration-api` service, pins the signed image from
`appolon1908-hue/Middleware-`, uses its default entrypoint and port `8080`, and
exposes no host port. Kong reaches the new N8N control-plane runtime only
through the external private `codestra-kong_kong_backend` network and stable
alias `middleware-integration-api`.

The API-completion deployment candidate is source
`f3437709c06747249586598590145234ea2c7327`, signed release run
`33617485810`, and immutable image digest
`sha256:a5c508fea8634351fb1bdd11e22a6cea520e436355cba3305456a07a3e0a2484`.
It selects the fail-closed `codestra-middleware-production-compose-v1`
runtime profile added specifically for Server A's private Compose topology.
Its migration head is `0006_outbox_attempt_events`. The signed release passed
middleware CI, production route-contract validation, SBOM generation,
vulnerability policy, provenance binding, and signature verification.

The first protected start reached PostgreSQL but stopped before serving because
the legacy `codestra_middleware` database reports unrelated Alembic revision
`0054_campaign_actions`. The canonical migration tool refused to guess or stamp
that lineage and applied no migration. The failed side-by-side container was
removed; the legacy runtime remained healthy. The reviewed replacement profile
therefore requires dedicated database `codestra_middleware_appolon` and role
`appolon_middleware_api`. This isolates the canonical SQL migration ledger and
prevents either runtime from changing the other's schema.

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
separate protected review and an exact-command operator apply after
configuration, DNS, authentication, migration, route, rollback, and readiness
validation. If any validation fails, the operator must first restore the
verified `0003_immutable_event_ledger` database backup and then restore the
captured `695fa3...` digest above. An image-only rollback is prohibited. This
change does not authorize that apply.
