# n8n governance

Existing production workflows under `/opt/codestra/n8n-workflows` were inventoried and preserved. New catalog metadata is under `n8n/control-plane`. Workflows use middleware-validated events, middleware APIs, correlation IDs, and idempotency keys; they never write directly to Odoo/VICIdial databases or call Postal/Jasmin internals.

Use separate development/staging/production projects and credentials, naming `CP-<number>-<system>-<purpose>-V<version>`, explicit owner metadata, the standard error workflow, bounded execution retention, Git exports, secret scanning, inactive import, synthetic acceptance, approval, then activation. Roll back by deactivating the new version and reactivating the prior approved export. High-impact SMS/email/mass-update workflows require safe-mode and approval gates.
