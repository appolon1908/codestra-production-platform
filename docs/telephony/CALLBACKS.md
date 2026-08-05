# Callbacks

Callbacks carry external callback ID, tenant/workspace/campaign, lead/customer
reference, agent, requested/scheduled aware timestamps, timezone, priority,
reason, state, attempts, result and middleware sync status. States range from
`REQUESTED` through `RECONCILIATION_REQUIRED`.

The adapter keys retries by external ID and the middleware idempotency key.
Changed payload under an existing key must be rejected and audited; production
callback calling remains disabled.

