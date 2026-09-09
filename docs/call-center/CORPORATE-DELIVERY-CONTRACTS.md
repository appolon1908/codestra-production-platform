# Corporate delivery: event receipts and orchestration attempts

## Source scope

This change adds the canonical VICIdial event consumer, registers `calling` as a
claimable delivery target, and separates n8n attempts from a stable business
operation. It does not deploy an adapter, configure a route, activate a worker,
change a live database, or enable any communication or telephony capability.

## Canonical event ingress

`POST /internal/v1/adapters/vicidial/events` accepts the envelope and signing
profile in `contracts/telephony/codestra-calling-api.v1.openapi.yaml`. The request
body is verified byte-for-byte. The authenticated TLS certificate must match
exactly one configured SHA-256 binding. The selected binding contains an exact
allowlist of `(tenant_id, business_unit_id, campaign_id, agent_id)` tuples and a
per-adapter HMAC secret-file reference. Caller-provided proxy/certificate headers
are not identities. Missing/unavailable binding, invalid signature, stale
signing time, wrong tuple, invalid schema, duplicate JSON keys and query strings
are rejected before any durable acceptance.

A valid request commits its original 202 receipt, event and `odoo`, `n8n`, and
`calling` outbox intents together. Exact retries retain the original receipt.
Changed bytes under the same identity conflict. Receipt rows cannot be updated
or deleted by the runtime role. No automatic receipt expiry is introduced; retain
them for at least the contract's seven-day replay boundary. Retention maintenance
requires its own reviewed policy and privileged execution, not a runtime DELETE.

The existing plain HTTP entrypoint recognizes the endpoint but rejects it without
an actual verified TLS socket. It must not trust `X-SSL-Client-Verify` or equivalent
headers. The optional dedicated listener is started only explicitly:

```text
python -m control_plane_service.calling_ingress
```

It requires `VICIDIAL_EVENT_INGRESS_ENABLED=true`, an explicitly chosen private
`VICIDIAL_EVENT_BIND_ADDRESS` and `VICIDIAL_EVENT_BIND_PORT`,
`VICIDIAL_EVENT_CLIENT_CA_FILE`, `VICIDIAL_EVENT_SERVER_CERT_FILE`,
`VICIDIAL_EVENT_SERVER_KEY_FILE`, `VICIDIAL_EVENT_BINDINGS_FILE`, and the existing
control-plane database configuration. The enable flag defaults off. No concrete
live address, port, key, certificate, or grant is assigned by this PR. The bindings
file is version `1` with a `bindings` array; each row has `certificate_sha256`,
`hmac_secret_file`, and `grants` (objects with those four exact identity keys).
Keep it outside Git and restrict access. Provision no wildcard grants.

## Attempt identity and recovery

`(tenant_id, event_id, workflow_key)` plus the canonical business request hash
identifies the operation. `orchestration_execution_id` identifies an n8n attempt,
not a new business operation. Each attempt is durably bound before dispatch;
changing its business identity is a conflict. Completed action receipts are
reused across attempts, and downstream request bytes/idempotency keys exclude
attempt-only metadata. Concurrent action dispatch still requires the owning
handler to honor the stable idempotency key; this is not a claim that concurrent
HTTP attempts can never occur. Unknown outcomes must be reconciled downstream.

Each callback has its own attempt-bound result identity. Its receipt, attempt
state, aggregate state and Odoo delivery intent commit atomically. Late failure
cannot downgrade completed business success. Existing error callbacks that resolve
an `unknown` tenant remain restricted to their registered execution binding.

## Schema and rollout boundary

Apply `migrations/control_plane/007_corporate_delivery_receipts.sql` only through
the separately approved database migration path, after the existing migration
chain including `006_delivery_leases_and_realtime.sql`. It adds the receipt and
attempt tables and backfills existing first-attempt mappings. No migration runs
at PostgreSQL application startup. Before rollout, verify least-privilege grants,
backup/restore and predecessor compatibility; retain durable receipts and mappings
on rollback rather than dropping state that prevents duplicate effects.

The source-head/current-merge transaction workflow runs on disposable PostgreSQL,
including repeated migration application, limited-role access, concurrent retries
and attempt recovery. The loopback TLS test uses ephemeral test-only certificates.
Neither workflow performs live provider delivery or runtime certification. Existing
external-write, n8n dispatch and calling kill switches remain independently required.
