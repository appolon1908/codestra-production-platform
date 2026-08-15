# Event model

The machine-readable contract is `schemas/integration-event-envelope-v1.schema.json`. Required producer fields are `event_type`, `event_version=1.0`, `occurred_at`, `tenant_id`, `idempotency_key`, and object `payload`. Middleware adds `event_id`, `received_at`, `source`, and a correlation ID when absent. Optional fields are customer, causation, correlation, and metadata.

Event names use `<system>.<entity>.<action>` and semantic versions. Unsupported versions or source/type mismatches return 422. The same tenant/source/idempotency key and exact envelope returns the prior result; a different envelope returns 409.
