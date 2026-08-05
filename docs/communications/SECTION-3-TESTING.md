# Section 3 staging test evidence

The local suite covers channel/message validation, denied consent, opt-out
blocking, approval requirements, duplicate idempotency keys, payload mismatch,
cross-tenant lookup, duplicate identity and human/AI assignment conflicts.
Provider delivery remains mocked and autonomous customer messaging is disabled.

The VICIdial server does not implement the middleware REST endpoints; it
supplies the provider-neutral contract and VOICE-side event boundary for review
and integration on `65.109.65.169`.

