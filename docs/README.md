# Documentation index

Use this directory for canonical documentation. Dated evidence and historical reports are not current runtime authority unless a current change record explicitly references them.

## Architecture

- `architecture/CODE_STRUCTURE.md` — target package boundaries and refactor rules.
- `architecture/API_GOVERNANCE.md` — API ownership, versioning, security, and route authority.
- `architecture/FEATURE_DELIVERY_PLAN.md` — ordered cleanup and feature-delivery program.
- `../ARCHITECTURE.md` — current high-level production architecture.
- `../CODESTRA_INTEGRATION_CONSTITUTION.md` — cross-system security constitution.

## API and schemas

- `openapi/control-plane-v1.yaml` — current control-plane OpenAPI authority.
- `../config/integration-registries.yaml` — connector, endpoint, webhook, and protocol registry.
- `../config/platform-catalog.yaml` — service, feature, critical API, and gap catalog.
- `../schemas/` — versioned data schemas.

## Operations

- `../DEPLOYMENT.md` — deployment overview.
- `../DISASTER_RECOVERY.md` — recovery overview.
- `../operations/runbooks/` — operational and alert runbooks.
- `../operations/shared-postgresql/` — shared PostgreSQL recovery authority.
- `../operations/caddy/` — edge configuration authority.
- `../operations/monitoring/` — monitoring and alert authority.

## Documentation rules

1. Do not add new mission, report, or completion documents at repository root.
2. Put enduring architecture in `docs/architecture/`.
3. Put API contracts in `docs/openapi/` or `schemas/`.
4. Put operational procedures in `operations/runbooks/`.
5. Put dated evidence in `reports/<system>/<date>/` or `artifacts/`.
6. A historical report must state that it is evidence, not desired state.
7. Update the catalogs and tests whenever an API, service, feature, owner, or activation boundary changes.
