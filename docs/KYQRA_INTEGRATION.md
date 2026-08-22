# Kyqra integration

Kyqra continues to use `10.40.0.1:8095` with its dedicated API key and HMAC secret. Normalized `kyqra.job.completed`, `kyqra.record.created`, and failure events are validated and deduplicated by middleware. Middleware maps provenance and invokes Odoo/n8n; Kyqra never accesses Odoo PostgreSQL or arbitrary n8n webhooks.
