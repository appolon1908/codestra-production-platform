# Control-plane API

- `GET /health`, `GET /ready`, `GET /metrics`
- `POST /api/v1/events/{kyqra|telnexa|klyrow|n8n|odoo}` — service API key plus `X-Timestamp`, `X-Event-Id`, `X-Signature`
- `GET /api/v1/ops/summary`, `GET /api/v1/ops/events`, `GET /api/v1/ops/correlations/{id}` — RBAC operator token
- `POST /api/v1/ops/events/{id}/replay`, `POST /api/v1/ops/integrations/{name}/pause|resume`
- `POST /api/v1/preferences`, `POST /api/v1/preferences/check`
- `POST /v1/messages/sms`, `POST /v1/messages/email` — bearer identity plus tenant, request/correlation IDs, and idempotency key
- `GET /v1/messages`, `GET /v1/messages/{id}`, `GET /v1/messages/{id}/events`
- `POST /v1/messages/{id}/cancel`, `POST /v1/messages/{id}/retry`
- `GET|PUT /v1/customers/{id}/preferences`
- `GET /v1/health`, `GET /v1/ready`

Errors are JSON `{ "error": "stable_code" }`. Rate-limited production ingress should return 429 and `Retry-After`; the existing ingress retains its current source/firewall controls while migration is staged.

The machine-readable OpenAPI 3.1 contract is `docs/openapi/control-plane-v1.yaml`. HMAC signs `timestamp + newline + event_id + newline + source + newline + exact request body`; timestamps outside the configured tolerance are rejected.
