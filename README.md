# Application Server A Package

## Middleware/n8n integration control plane

The additive P0 control plane is in `control_plane_service/` with its Docker deployment under `deploy/control-plane/`. It provides the unified event contract, independent service authentication, HMAC/replay defense, tenant-scoped idempotency, consent enforcement, durable queue/DLQ state, correlation history, RBAC operations APIs, audit records, and Prometheus metrics. It preserves the existing production ingress at `10.40.0.1:8095` and deploys loopback-only at `127.0.0.1:8096` with outbound Odoo/n8n delivery disabled until approved credentials and workflows pass synthetic acceptance.

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
