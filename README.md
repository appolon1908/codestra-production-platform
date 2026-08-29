# Application Server A Package

## Repository authority status

This repository is retained as **historical deployment, runtime-reconciliation and rollback evidence** for Application Server A and earlier coordinated production-activation work.

It is **not the central release-authority repository for the current Codestra architecture**. Current services ship independently from their owning repositories and couple through versioned contracts. A multi-repository feature is considered released only when its participating repositories have immutable source/artifact identities and a cross-repository evidence note; no mutable central manifest may silently override a product repository's accepted source.

Future shared API-edge Caddy source belongs with the gateway/edge authority in `appolon1908-hue/Kong` under the reviewed Caddy edge model. Existing Caddy/runtime material in this repository remains migration/reconciliation evidence until explicitly ported or retired through a separate, read-back-verified cutover.

Do not delete historical manifests, checksums, backup references, rollback evidence or runtime reconciliation records merely because authority has moved. They remain evidence for previously deployed states.

## Historical Middleware/n8n integration control plane

The additive P0 control plane is in `control_plane_service/` with its Docker deployment under `deploy/control-plane/`. It provides the unified event contract, independent service authentication, HMAC/replay defense, tenant-scoped idempotency, consent enforcement, durable queue/DLQ state, correlation history, RBAC operations APIs, audit records, and Prometheus metrics. It preserves the existing production ingress at `10.40.0.1:8095` and deploys loopback-only at `127.0.0.1:8096` with outbound Odoo/n8n delivery disabled until approved credentials and workflows pass synthetic acceptance.

The communications API adds `POST /v1/messages/sms`, `POST /v1/messages/email`, tenant-scoped message/timeline queries, preference APIs, cancel/retry controls, Telnexa simulator dispatch, and Klyrow test dispatch. Production delivery has two independent fail-closed gates: `CONTROL_PLANE_OUTBOUND_ENABLED` and `CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED`; the committed Compose contract keeps outbound disabled and the provider modes non-production.

See `ARCHITECTURE.md`, `DEPLOYMENT.md`, `SECURITY.md`, `DISASTER_RECOVERY.md`, and `docs/` for historical contracts and operations.

Server: `65.109.65.169`

Historical target directory:

```text
/root/codestra-production-completion
```

This package installed the application-side Codex directive for Odoo 19, middleware, automatic campaign design/provisioning, n8n, Redis, Keycloak, reverse proxy, monitoring, GitHub CI, and deployment.

## Historical upload procedure

The following procedure is preserved for audit/history and is not the current cross-repository release model.

Download these two files into the same Windows Downloads folder:

- `codestra_app_server_A_65.109.65.169.zip`
- `upload_app_server_A_65.109.65.169.ps1`

Run PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$env:USERPROFILE\Downloads\upload_app_server_A_65.109.65.169.ps1"
```

Historical Codex start command:

```powershell
ssh -t root@65.109.65.169 "cd /root/codestra-production-completion && ./start-codex-app-server.sh"
```

Do not treat this historical package/start procedure as permission to deploy current services. Current deployments must originate from the owning repository's reviewed immutable artifact and independent release gates.

Do not place passwords or production secrets in Git-tracked files.
