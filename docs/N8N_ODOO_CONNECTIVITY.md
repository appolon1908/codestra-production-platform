# n8n and Odoo Connectivity

## Odoo

- Middleware -> Odoo network PASS: live `200 {"status":"pass"}` to `/web/health`.
- Odoo -> Middleware network PASS: live 200 from Odoo to control-plane `/health`.
- Functional/auth BLOCKED: Odoo has no control-plane credential and the control plane has no `CONTROL_PLANE_ODOO_URL`.
- No application direct Odoo PostgreSQL connection/write code was found. Audit SQL was read-only.
- `codestra_integration_hub` is installed, but no safe authenticated callback was available for a business-record test.

## n8n

- Middleware -> n8n network PASS: live 200 to `/healthz`.
- n8n -> Middleware network PASS: live 200 from n8n to `/health`.
- Functional/auth BLOCKED: n8n has no middleware credential; the control plane has no `CONTROL_PLANE_N8N_URL`.
- Production database: 20 workflows, all inactive/unarchived; zero webhook registrations and zero credential records. Nothing was activated or deleted.
- Both Odoo and n8n control-plane source identities passed valid and negative bearer/HMAC, replay, conflict, and correlation tests server-side.
