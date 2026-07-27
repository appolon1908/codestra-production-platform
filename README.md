# Dedicated VICIdial Server Package

Server: `65.21.67.207`

Target directory:

```text
/root/codestra-vicidial-completion
```

This package installs the VICIdial-side Codex directive and restricted adapter contract. It does not install Odoo, n8n, or the main middleware service.

## Upload from Windows PowerShell

Download these two files into the same Windows Downloads folder:

- `codestra_vicidial_server_65.21.67.207.zip`
- `upload_vicidial_server_65.21.67.207.ps1`

Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "$env:USERPROFILE\Downloads\upload_vicidial_server_65.21.67.207.ps1"
```

## Start Codex after installation

```powershell
ssh -t root@65.21.67.207 "cd /root/codestra-vicidial-completion && ./start-codex-vicidial.sh"
```

Codex is instructed to begin read-only and preserve the current working phone system.

## Implemented adapter

The restricted adapter source is in `src/codestra_vicidial`. It implements the
allowlisted campaign, agent, lead, callback, script, disposition, transfer
policy, and reconciliation contract. All write flags default to false and there
is no production activation route.

Run the offline suite with the available isolated test environment:

```bash
PYTHONPATH=src /root/codestra-vicidial-edge/.test-venv/bin/pytest -q
```

This repository does not automatically deploy or restart the running telephony
services. See `docs/ADAPTER_OPERATIONS.md` and the reports under
`reports/vicidial/` before an approved staging change.
