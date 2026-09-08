# Codestra Production Platform

## Integration and release authority

This repository is the protected integration and release authority for the
Codestra platform. Its long-lived baseline is
`release/production-activation`; application repositories continue to own
their service source, while this repository owns the cross-service contract
catalog, runtime composition, immutable multi-service release manifests,
integrated edge configuration, preflight, promotion, rollback orchestration,
and release evidence.

Canonical control locations:

| Responsibility | Canonical path |
|---|---|
| Cross-service contract catalog | `contracts/catalog.v1.json` |
| Runtime composition | `composition/runtime-composition.v1.json` and the referenced files under `deploy/` |
| Multi-service release manifest contract | `release/platform-release-manifest.v1.schema.json` |
| Release-manifest operating rules | `release/README.md` |
| Caddy desired state | `operations/caddy/` |
| Kong desired state | `deploy/kong/` |
| Release evidence and go/no-go records | `evidence/` and approved release artifacts |

`operations/caddy/` is Caddy's Git home. Host files under `/etc/caddy` are a
deployed projection and must not become an unreviewed source of truth. The
Middleware `platform/caddy` branch remains a review and compatibility
workstream; it does not own production Caddy deployment files.

The canonical crawler source is
[`appolon1908-hue/kyqra-crawler`](https://github.com/appolon1908-hue/kyqra-crawler).
The legacy `appolon1908-hue/kyqra` name is retired and must not be introduced
into contracts, composition, release manifests, or deployment documentation.

This repository also contains reviewed platform contracts, deployment definitions, security policy, recovery tooling, monitoring, and the integration control plane used by Odoo, Middleware, n8n, Keycloak, Kong, Redis, PostgreSQL, VICIdial, Klyrow, Telnexa, and Kyqra.

A merged source change is **not** proof that the corresponding production runtime is active. Production deployment requires an immutable image or package built from the protected merged SHA, a current change record, recovery evidence, an approved maintenance window, canary/rollback evidence, and live-versus-Git reconciliation.

## Production request path

```text
Public client
  -> host Caddy (public TLS edge)
  -> Docker upstream-gateway
  -> private Kong
  -> private middleware/control-plane service
  -> private PostgreSQL, Redis, NATS, Odoo, n8n, or approved provider adapter
```

Business APIs must not bypass Kong. Explicit exceptions are limited to reviewed browser applications, public health contracts, and private mTLS receivers. Kong Admin, PostgreSQL, Redis, NATS, middleware application ports, and internal provider listeners must remain private.

## Repository map

| Path | Responsibility |
| --- | --- |
| `control_plane_service/` | Authenticated integration control plane and durable coordination APIs |
| `campaign_provisioning/` | Campaign and provisioning domain logic |
| `eventing/` | Event contracts and durable event handling |
| `integrations/` | Restricted adapters and integration-specific source |
| `deploy/` | Source-controlled Compose, Kong, and service deployment definitions |
| `operations/` | Caddy, monitoring, recovery, database, systemd, and operational controls |
| `config/` | Canonical policy, service, feature, connector, and API registries |
| `schemas/` | Versioned machine-readable data contracts |
| `n8n/` | Governed workflow source; production activation remains separate |
| `odoo_addons/` | Platform-owned Odoo integration addons and validation fixtures |
| `tools/` | Fail-closed source and architecture validators |
| `tests/` | Clean-checkout source, security, contract, and recovery tests |
| `docs/` | Canonical architecture, API, deployment, and runbook documentation |
| `reports/`, `artifacts/`, dated root reports | Historical evidence, not current runtime authority |

## Canonical catalogs

- Cross-service contract catalog: `contracts/catalog.v1.json`
- Runtime composition: `composition/runtime-composition.v1.json`
- System boundaries and allowed connections: `config/integration-policy.yaml`
- Connectors, endpoints, webhooks, and protocols: `config/integration-registries.yaml`
- Platform features, critical API surface, and known gaps: `config/platform-catalog.yaml`
- Platform structure validator: `tools/check_platform_catalog.py`
- Integration constitution validator: `tools/check_integration_architecture.py`
- Human-readable architecture: `ARCHITECTURE.md`
- Documentation index: `docs/README.md`

## Change boundaries

Keep these concerns in separate pull requests unless a reviewed migration requires them to move together:

1. API and schema contracts.
2. Application/domain implementation.
3. Database migrations and recovery authority.
4. Gateway/Caddy routing.
5. Runtime Compose and immutable image references.
6. Production activation and capability flags.

Do not combine Kong database HA, shared PostgreSQL PITR, middleware deployment, Odoo module activation, telephony activation, and provider delivery in one release.

## Local validation

```bash
python -m pytest -q
python tools/check_integration_architecture.py
python tools/check_platform_catalog.py
python -m compileall -q control_plane_service campaign_provisioning eventing integrations tools
```

Run the deployment-specific catalog gate for the features included in a release:

```bash
python tools/check_platform_catalog.py \
  --deployment-check \
  --feature middleware-callback-api \
  --feature middleware-campaign-automation
```

The deployment check is expected to fail while a required source or runtime gap is unresolved.

## Production rule

Never deploy from a dirty checkout, an unreviewed feature branch, a mutable tag, or a generated container name treated as permanent service authority. Deploy only the approved immutable artifact from the protected merged SHA, recreate only the affected services, preserve the host-Caddy -> upstream-gateway -> Kong architecture, and keep all dangerous capabilities disabled until separately certified.

Do not commit credentials, private keys, live certificates, database data, backups, recordings, runtime logs, or customer data.
