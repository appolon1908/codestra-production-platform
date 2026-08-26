# Disaster recovery

Back up the SQLite database with its online backup API, workflow exports, repository commit SHA, runtime environment checksum (not its contents), Compose/reverse-proxy configuration, Odoo database/filestore pair, and n8n database/configuration. Store encrypted copies off-host.

On a clean server: restore Docker and private networking, deploy the recorded commit, restore secrets from approved storage, restore the control-plane database, restore Odoo database and matching filestore, restore n8n database and encryption key, import workflows inactive, then validate health, tenant isolation, consent, idempotency, correlation, queue/DLQ, and synthetic adapters before enabling delivery. Reconcile queued events before resuming producers.
