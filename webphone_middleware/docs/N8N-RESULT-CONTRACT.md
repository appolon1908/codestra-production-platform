# n8n result contract

The canonical callback is `POST /api/v1/n8n-runtime/results` with schema
`codestra.n8n.result.v1`. It binds workflow code/version, execution,
correlation, tenant, status, timestamp, and bounded result data.

Required headers bind identity, tenant, workflow, execution, correlation,
timestamp, nonce, exact body SHA-256, and HMAC version 1 signature. The HMAC
secret is read from a protected file. Nonces are recorded durably before the
transaction commits; replay, stale timestamp, modified body, cross-tenant
binding, unknown schema, and unknown fields fail closed.

Results never directly mutate Odoo or VICIdial. They become durable middleware
records for an independently governed adapter/outbox.
