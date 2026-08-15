# n8n and Odoo Connectivity

Odoo and n8n ingress use the same signed event contract. Odoo events deliver to n8n; n8n events deliver to Odoo; provider events fan out to both. The worker forwards the stored correlation ID and applies bounded retry/DLQ behavior.

The Git-managed workflow manifest contains nine inactive control-plane workflows: three Kyqra, three Telnexa, and three Klyrow workflows. They are inactive by design and contain no credentials. No live n8n API/editor or Odoo runtime exists on the current host, so IDs, activation state, credential bindings, error workflows, read-only Odoo queries, safe records, and reverse callbacks are BLOCKED. Source search found no control-plane connection to Odoo PostgreSQL and no direct application DB writes.
