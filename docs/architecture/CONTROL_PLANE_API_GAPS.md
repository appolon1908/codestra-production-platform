# Control-plane API coverage gaps

The control plane already implements more routes than its OpenAPI, Kong, and endpoint registry currently describe. The exact inventory is `config/control-plane-api-surface.yaml`; `tools/check_control_plane_api_surface.py` verifies that entries marked present actually exist and that every request-path literal in `control_plane_service/server.py` is represented.

Normal source validation passes when a missing layer is explicitly declared as a gap with an owner and remediation. The pre-deployment command fails closed until all gaps selected for release are resolved:

```bash
python tools/check_control_plane_api_surface.py --strict
```

## Main missing contract groups

### Health and release identity aliases

`/healthz`, `/v1/health`, `/livez`, `/readyz`, `/v1/ready`, `/version`, and the public `/api/v1/health` alias are not consistently represented across OpenAPI and the endpoint registry. Each alias must be documented with a lifecycle or removed.

### CRM gateway

The customer account, lead read/create/update, and activity-create routes are implemented but absent from OpenAPI and the endpoint registry. They require exact schemas, customer-gateway identity, idempotency conflict behavior, field allowlists, and Odoo dependency errors.

### Platform administration

`/v1/admin/system/health`, `/readiness`, and `/databases` are implemented under the broad Kong admin route but are not documented or registered individually. Their responses must remain sanitized and restricted to `platform.admin`.

### Messaging and preferences

The public message command, dispatch, result, timeline, cancel/retry, and preference mutation APIs are incomplete across OpenAPI, Kong, and the registry. These must define state preconditions, idempotency, consent/suppression errors, audit behavior, and tenant isolation.

### Crawler operations

Create is documented, but status, results, cancel, and retry contracts are not. These remain staging-only until response schemas, retry limits, safe-target policy, and provider reconciliation are merged.

### Operations and reconciliation

Operations summary/events are documented but not routed by Kong. Correlation lookup, event replay, integration pause/resume, mapping job status/results, and the implemented `/api/v1/reconciliation/run` path need one canonical contract and exact gateway scope.

### Postal inbound and website forms

Postal inbound is implemented as a private authenticated integration but lacks a published bounded MIME/replay/idempotency contract. The forms implementation currently handles `/v1/forms/{form_id}`, while the registry declares `/v1/forms/{form_id}/submit`; one path must become canonical before deployment.

## Implementation order

1. Merge the platform catalog and route-authority foundations.
2. Decide canonical aliases and remove undocumented duplicates.
3. Expand OpenAPI and the endpoint registry without changing runtime behavior.
4. Add exact Kong routes/scopes only for APIs approved for public exposure.
5. Add contract tests for authentication, tenant, idempotency, request IDs, rate/size limits, and errors.
6. Generate clients only after the exact contracts merge.
7. Refactor the monolithic handler after coverage is locked by tests.

This inventory does not authorize live delivery or a server deployment.
