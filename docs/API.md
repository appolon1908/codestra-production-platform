# Control-plane API

- `GET /health`, `GET /ready`, `GET /metrics`
- `POST /api/v1/events/{kyqra|telnexa|klyrow|n8n|odoo}` — service API key plus `X-Timestamp`, `X-Event-Id`, `X-Signature`
- `GET /api/v1/ops/summary`, `GET /api/v1/ops/events`, `GET /api/v1/ops/correlations/{id}` — RBAC operator token
- `POST /api/v1/ops/events/{id}/replay`, `POST /api/v1/ops/integrations/{name}/pause|resume`
- `POST /api/v1/preferences`, `POST /api/v1/preferences/check`

Errors are JSON `{ "error": "stable_code" }`. Rate-limited production ingress should return 429 and `Retry-After`; the existing ingress retains its current source/firewall controls while migration is staged.
