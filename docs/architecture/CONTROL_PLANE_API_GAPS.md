# Control-plane API coverage gaps

The control plane already implements more routes than its OpenAPI, Kong, and endpoint registry currently describe. The exact contract inventory is `config/control-plane-api-surface.yaml`. Method-bound implementation and behavioral proof is kept separately in `config/control-plane-api-assurance.yaml`, so desired contracts are not confused with code that has actually been proven.

`tools/check_control_plane_api_surface.py` now verifies all of the following:

- every declared route token occurs inside the handler for the declared HTTP method;
- delegated CRM routes bind to their explicit helper and allowed methods;
- dynamic message-detail, timeline, crawler-status, and crawler-result branches retain exact branch evidence;
- idempotency marked `required` is either backed by implementation tokens plus a behavioral regression test or reported as an implementation gap;
- gateway authentication mismatches are reported separately from simple route presence;
- entries marked present in OpenAPI, Kong, and the endpoint registry actually exist;
- every method-specific request-path predicate in `control_plane_service/server.py` is represented.

Normal source validation passes when a missing layer is explicitly declared as a gap with an owner and remediation. The pre-deployment command fails closed until both contract gaps and implementation-assurance gaps selected for release are resolved:

```bash
python tools/check_control_plane_api_surface.py --strict
```

## Main missing contract groups

### Health and release identity aliases

`/healthz`, `/v1/health`, `/livez`, `/readyz`, `/v1/ready`, `/version`, and the public `/api/v1/health` alias are not consistently represented across OpenAPI and the endpoint registry. Each alias must be documented with a lifecycle or removed.

### CRM gateway

The customer account, lead read/create/update, and activity-create routes are implemented but absent from OpenAPI and the endpoint registry. They require exact schemas, customer-gateway identity, idempotency conflict behavior, field allowlists, and Odoo dependency errors. Lead creation has behavioral idempotency evidence; activity creation and lead update remain explicit endpoint-test gaps.

### Platform administration

`/v1/admin/system/health`, `/readiness`, and `/databases` are implemented under the broad Kong admin route but are not documented or registered individually. Their responses must remain sanitized and restricted to `platform.admin`.

### Messaging and preferences

The public message command, dispatch, result, timeline, cancel/retry, and preference mutation APIs are incomplete across OpenAPI, Kong, and the registry. Message creation has behavioral idempotency evidence. Dispatch, provider-result, cancel/retry, and preference mutations remain implementation gaps until repeated commands are proven safe. These contracts must also define state preconditions, consent/suppression errors, audit behavior, and tenant isolation.

### Crawler operations

Create is documented and its storage-level idempotency is covered by a regression test. Status, results, cancel, and retry contracts are not complete. Cancel and retry currently invoke the provider on every POST, so both remain explicit idempotency implementation gaps. These APIs stay staging-only until response schemas, command deduplication, retry limits, safe-target policy, and provider reconciliation are merged.

### Operations and reconciliation

Operations summary/events are documented but not routed by Kong. Correlation lookup, event replay, integration pause/resume, mapping job status/results, and the implemented `/api/v1/reconciliation/run` path need one canonical contract and exact gateway scope. Replay and pause/resume also require durable command idempotency.

### Postal inbound and website forms

Postal inbound and form submission have behavioral duplicate/conflict tests, but their published OpenAPI and registry contracts remain incomplete. The forms implementation currently handles `/v1/forms/{form_id}`, while the registry declares `/v1/forms/{form_id}/submit`; one path must become canonical before deployment.

### Event-ingest gateway authentication

`POST /api/v1/events/{source}` validates service API keys and HMAC signatures in the handler. The current Kong service applies OIDC and tenant-claim enforcement to that route before the request reaches the handler. Route presence is therefore not authentication compatibility. The assurance gate records this as a gateway-authentication gap until a dedicated HMAC route or reviewed OIDC-to-service-HMAC translation is merged.

## Implementation order

1. Merge the platform catalog and route-authority foundations.
2. Decide canonical aliases and remove undocumented duplicates.
3. Expand OpenAPI and the endpoint registry without changing runtime behavior.
4. Add exact Kong routes and authentication profiles only for APIs approved for public exposure.
5. Close idempotency implementation gaps with durable command records and behavioral duplicate/conflict tests.
6. Add contract tests for authentication, tenant isolation, request IDs, rate/size limits, and errors.
7. Generate clients only after the exact contracts merge.
8. Refactor the monolithic handler after coverage is locked by method-bound tests.

This inventory and assurance package do not authorize live delivery or a server deployment.
