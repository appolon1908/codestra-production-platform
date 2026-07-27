# Application Server A Package

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
