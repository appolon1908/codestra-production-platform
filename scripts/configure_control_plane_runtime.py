#!/usr/bin/env python3
"""Provision local-only integration credentials and import governed n8n workflows.

Secrets are generated on the host, written only to root-owned runtime storage, and
passed to Odoo/n8n over stdin or short-lived mode-0600 files. Nothing is printed.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = Path(os.getenv("CONTROL_PLANE_ENV_FILE", "/etc/codestra/secrets/control-plane.env"))
ODOO_CONTROLLER = Path(os.getenv("ODOO_EVENT_CONTROLLER", "/opt/codestra/staging-sources/app-odoo-identity-timezone-57ab123cded2-r2/integration/codestra_vicidial_crm/controllers/api.py"))


def run(command: list[str], *, stdin: str | None = None) -> None:
    subprocess.run(command, input=stdin, text=True, check=True, stdout=subprocess.DEVNULL)


def token() -> str:
    return secrets.token_urlsafe(48)


def update_env(values: dict[str, str]) -> None:
    current: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1); current[key] = value
    for key, value in values.items():
        current[key] = value
    temporary = ENV.with_suffix(".new")
    temporary.write_text("".join(f"{key}={value}\n" for key, value in sorted(current.items())))
    os.chmod(temporary, 0o600); os.replace(temporary, ENV)


def repair_odoo_controller() -> None:
    """Apply the Odoo 19 required-field compatibility fix idempotently."""
    raw = ODOO_CONTROLLER.read_text()
    if '"source": "middleware"' in raw: return
    old = '            "event_type": payload["event_type"],\n            "source_system": "external",\n            "destination_system": "odoo",\n'
    new = '            "event_type": payload["event_type"],\n            "source": "middleware",\n            "destination": "odoo",\n            "source_system": "external",\n            "destination_system": "odoo",\n            "correlation_id": payload.get("correlation_id"),\n'
    if old not in raw: raise RuntimeError("unsupported_odoo_controller_version")
    temporary = ODOO_CONTROLLER.with_suffix(".py.new"); temporary.write_text(raw.replace(old,new,1)); os.chmod(temporary,0o644); os.replace(temporary,ODOO_CONTROLLER)


def main() -> None:
    repair_odoo_controller()
    existing = dict(line.split("=", 1) for line in ENV.read_text().splitlines() if "=" in line)
    values = {
        "N8N_MIDDLEWARE_API_KEY": existing.get("N8N_MIDDLEWARE_API_KEY") or token(),
        "ODOO_OUTBOUND_HMAC_SECRET": existing.get("ODOO_OUTBOUND_HMAC_SECRET") or token(),
        "N8N_OUTBOUND_API_KEY": existing.get("N8N_OUTBOUND_API_KEY") or token(),
        "N8N_MIDDLEWARE_HMAC_SECRET": existing.get("N8N_MIDDLEWARE_HMAC_SECRET") or token(),
        "ODOO_SERVICE_PASSWORD": existing.get("ODOO_SERVICE_PASSWORD") or token(),
        "CONTROL_PLANE_ODOO_URL": "http://codestra-odoo-1:8069/codestra/api/v1/events",
        "CONTROL_PLANE_N8N_URL": "http://codestra-n8n-1:5678/webhook/codestra-{event_type}",
        "ODOO_BASE_URL": "http://codestra-odoo-1:8069", "N8N_BASE_URL": "http://codestra-n8n-1:5678",
        "TELNEXA_BASE_URL": "https://10.40.0.4/telnexa", "KLYROW_BASE_URL": "https://10.40.0.4/klyrow",
        "KYQRA_BASE_URL": "http://kyqra:3100", "KYQRA_MODE": "test",
        "TELNEXA_MODE": "simulator", "KLYROW_MODE": "test", "CONTROL_PLANE_OUTBOUND_ENABLED": "true",
    }
    update_env(values)

    odoo_code = """import os
secret=os.environ['CP_ODOO_SECRET']; password=os.environ['CP_ODOO_PASSWORD']
env['ir.config_parameter'].sudo().set_param('codestra.webhook_secret', secret)
env['ir.config_parameter'].sudo().set_param('codestra.middleware_api_key', os.environ['CP_INBOUND_KEY'])
env['ir.config_parameter'].sudo().set_param('codestra.middleware_hmac_secret', os.environ['CP_INBOUND_SECRET'])
env['ir.config_parameter'].sudo().set_param('codestra.middleware_url', 'http://codestra-integration-control-plane-api-1:8096/api/v1/events/odoo')
users=env['res.users'].sudo(); login='codestra.middleware@service.internal'; user=users.search([('login','=',login)],limit=1)
groups=[env.ref('base.group_user').id,env.ref('base.group_partner_manager').id]
vals={'name':'Codestra Middleware Service','login':login,'password':password,'active':True,'share':False,'group_ids':[(6,0,groups)]}
user.write(vals) if user else users.create(vals)
env.cr.commit()
"""
    odoo_env = os.environ.copy(); odoo_env.update(CP_ODOO_SECRET=values["ODOO_OUTBOUND_HMAC_SECRET"], CP_ODOO_PASSWORD=values["ODOO_SERVICE_PASSWORD"], CP_INBOUND_KEY=existing["ODOO_MIDDLEWARE_API_KEY"], CP_INBOUND_SECRET=existing["ODOO_WEBHOOK_SECRET"])
    shell_command = 'odoo shell -d "$DB_NAME" --db_password="$(cat /run/secrets/odoo_db_password)"'
    subprocess.run(["docker", "exec", "-i", "-e", "CP_ODOO_SECRET", "-e", "CP_ODOO_PASSWORD", "-e", "CP_INBOUND_KEY", "-e", "CP_INBOUND_SECRET", "codestra-odoo-1", "sh", "-lc", shell_command], input=odoo_code, text=True, check=True, env=odoo_env, stdout=subprocess.DEVNULL)

    credential = [
        {"id": "codestraMiddlewareHeaderAuth", "name": "Codestra Middleware Header Auth", "type": "httpHeaderAuth", "data": {"name": "Authorization", "value": "Bearer " + values["N8N_OUTBOUND_API_KEY"]}},
        {"id": "codestraMiddlewareEventSigner", "name": "Codestra Middleware Event Signer", "type": "httpCustomAuth", "data": {"json": json.dumps({"headers": {"Authorization": "Bearer " + existing["N8N_MIDDLEWARE_API_KEY"], "X-Codestra-HMAC-Secret": existing["N8N_WEBHOOK_SECRET"]}})}},
    ]
    workflows = subprocess.check_output([sys.executable, str(ROOT / "scripts/build_control_plane_workflows.py")], text=True)
    with tempfile.TemporaryDirectory() as directory:
        credential_path=Path(directory)/"credential.json"; workflow_path=Path(directory)/"workflows.json"
        credential_path.write_text(json.dumps(credential)); workflow_path.write_text(workflows)
        os.chmod(credential_path,0o600); os.chmod(workflow_path,0o600)
        run(["docker","cp",str(credential_path),"codestra-n8n-1:/tmp/codestra-credential.json"])
        run(["docker","cp",str(workflow_path),"codestra-n8n-1:/tmp/codestra-workflows.json"])
    run(["docker","exec","-u","0","codestra-n8n-1","chown","node:node","/tmp/codestra-credential.json","/tmp/codestra-workflows.json"])
    run(["docker","exec","codestra-n8n-1","n8n","import:credentials","--input=/tmp/codestra-credential.json"])
    run(["docker","exec","codestra-n8n-1","n8n","import:workflow","--input=/tmp/codestra-workflows.json"])
    # Import inactive. Activation is a separate acceptance-gated operation.
    run(["docker","exec","codestra-n8n-1","rm","-f","/tmp/codestra-credential.json","/tmp/codestra-workflows.json"])


if __name__ == "__main__": main()
