# Application Server A Package

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

## Middleware/n8n integration control plane

The additive P0 control plane is in `control_plane_service/` with its Docker deployment under `deploy/control-plane/`. It provides the unified event contract, independent service authentication, HMAC/replay defense, tenant-scoped idempotency, consent enforcement, durable queue/DLQ state, correlation history, RBAC operations APIs, audit records, and Prometheus metrics. It preserves the existing production ingress at `10.40.0.1:8095` and deploys loopback-only at `127.0.0.1:8096` with outbound Odoo/n8n delivery disabled until approved credentials and workflows pass synthetic acceptance.

The communications API adds `POST /v1/messages/sms`, `POST /v1/messages/email`, tenant-scoped message/timeline queries, preference APIs, cancel/retry controls, Telnexa simulator dispatch, and Klyrow test dispatch. Production delivery has two independent fail-closed gates: `CONTROL_PLANE_OUTBOUND_ENABLED` and `CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED`; the committed Compose contract keeps outbound disabled and the provider modes non-production.

See `ARCHITECTURE.md`, `DEPLOYMENT.md`, `SECURITY.md`, `DISASTER_RECOVERY.md`, and `docs/` for contracts and operations.

Server: `65.109.65.169`

Target directory:

```text
/root/codestra-production-completion
```

This package installs the application-side Codex directive for Odoo 19, middleware, automatic campaign design/provisioning, n8n, Redis, Keycloak, reverse proxy, monitoring, GitHub CI, and deployment.

## Upload from Windows PowerShell

Download these two files into the same Windows Downloads folder:

- `codestra_app_server_A_65.109.65.169.zip`
- `upload_app_server_A_65.109.65.169.ps1`

Run PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$env:USERPROFILE\Downloads\upload_app_server_A_65.109.65.169.ps1"
```

## Start Codex after installation

```powershell
ssh -t root@65.109.65.169 "cd /root/codestra-production-completion && ./start-codex-app-server.sh"
```

Do not place passwords or production secrets in Git-tracked files.
