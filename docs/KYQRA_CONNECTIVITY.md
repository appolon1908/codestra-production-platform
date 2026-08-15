# Kyqra Connectivity

`POST /v1/crawler/jobs` now provides the missing outbound direction. Default test mode accepts only localhost or reserved `example.*` targets, returns `test-job-*`, persists correlation and tenant scope, and deduplicates by tenant/idempotency key. Production is fail-closed and restricted to the private provider URL.

Inbound progress/completed/failed/result event families use service-key + HMAC, replay protection, idempotency, correlation and Odoo/n8n fanout. A real Crawlee/Playwright worker was not discovered on this host, so production lifecycle evidence is BLOCKED.
